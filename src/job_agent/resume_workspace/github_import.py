"""Credential-free public GitHub downloads; fixed hosts, no shell/git execution."""
from __future__ import annotations
import ipaddress
import json
import re
import socket
import tomllib
from io import BytesIO
from zipfile import ZipFile,BadZipFile
from urllib.parse import quote,urlsplit
import httpx
from pydantic import Field
from job_agent.schemas import StrictModel
from job_agent.resume_workspace.repository import WorkspaceConflict
from job_agent.resume_workspace.project_import import MAX_ARCHIVE_BYTES,scan_zip


class GitHubImport(StrictModel):
    url: str=Field(min_length=1,max_length=300)
    ref: str=Field(default='',max_length=150)


def repository_slug(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.netloc!='github.com' or parsed.query or parsed.fragment:
        raise WorkspaceConflict('github_public_https_url_required')
    match=re.fullmatch(r'/([A-Za-z0-9_.-]{1,80})/([A-Za-z0-9_.-]{1,100})/?',parsed.path)
    if not match:raise WorkspaceConflict('github_repository_url_required')
    owner,repo=match.groups();repo=repo.removesuffix('.git')
    if owner in ('.','..') or repo in ('','.','..'):raise WorkspaceConflict('github_repository_url_required')
    return owner,repo


def check_public_host(host):
    if host not in {'api.github.com','codeload.github.com'}:raise WorkspaceConflict('github_host_not_allowed')
    try:addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    except OSError as exc:raise WorkspaceConflict('github_dns_unavailable') from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise WorkspaceConflict('github_private_address_rejected')


class PublicGitHubImporter:
    def __init__(self,store,*,client=None,host_guard=check_public_host):
        self.store=store;self.client=client;self.host_guard=host_guard

    def _download(self,client,url,limit):
        parsed=urlsplit(url);self.host_guard(parsed.hostname)
        try:
            with client.stream('GET',url,headers={'User-Agent':'JobAgentV3-public-import','Accept':'application/vnd.github+json'}) as response:
                if response.is_redirect:raise WorkspaceConflict('github_redirect_rejected')
                if response.status_code in (403,429) and (response.headers.get('x-ratelimit-remaining')=='0' or response.status_code==429):
                    raise WorkspaceConflict('github_rate_limit_exceeded_try_zip')
                if response.status_code!=200:raise WorkspaceConflict('github_public_repository_unavailable')
                body=bytearray()
                for chunk in response.iter_bytes():
                    if len(body)+len(chunk)>limit:raise WorkspaceConflict('github_download_limit')
                    body.extend(chunk)
                return bytes(body)
        except httpx.HTTPError as exc:raise WorkspaceConflict('github_download_unavailable') from exc

    def import_project(self,owner,project_id,request:GitHubImport):
        self.store.get_project(owner,project_id)
        user,repo=repository_slug(request.url)
        if request.ref and not re.fullmatch(r'[A-Za-z0-9_.\-/]{1,150}',request.ref):raise WorkspaceConflict('github_ref_invalid')
        supplied=self.client is not None
        client=self.client or httpx.Client(timeout=httpx.Timeout(25,connect=8),trust_env=False,follow_redirects=False)
        try:
            if re.fullmatch(r'[a-fA-F0-9]{40}',request.ref):
                # A full immutable SHA needs no branch resolver. The anonymous
                # official endpoint must return its git-archive commit comment,
                # so a 40-hex branch name cannot masquerade as a different commit.
                commit=request.ref.casefold()
                raw=self._download(client,f'https://codeload.github.com/{user}/{repo}/zip/{commit}',MAX_ARCHIVE_BYTES)
                try:
                    with ZipFile(BytesIO(raw)) as archive:
                        if archive.comment.strip().decode('ascii').casefold()!=commit:raise WorkspaceConflict('github_archive_commit_mismatch')
                except (BadZipFile,UnicodeDecodeError) as exc:raise WorkspaceConflict('github_archive_commit_unverifiable') from exc
                files,safety=scan_zip(raw,strip_single_root=True)
                try:
                    declaration=tomllib.loads(files.get('pyproject.toml','')).get('project',{}).get('license','UNKNOWN')
                    license_value=declaration.get('text','UNKNOWN') if isinstance(declaration,dict) else declaration
                    if not isinstance(license_value,str) or len(license_value)>120:license_value='UNKNOWN'
                except (tomllib.TOMLDecodeError,TypeError):license_value='UNKNOWN'
                return self.store.publish_files(owner,project_id,files,origin='github',commit_sha=commit,metadata={
                    **safety,'repository_url':f'https://github.com/{user}/{repo}','license':license_value,
                    'license_basis':'upstream_pyproject_declaration_not_legal_review','source_ref':commit,
                    'public_access_basis':'anonymous_official_codeload','commit_verified_by':'git_archive_comment',
                    'private':False,'contribution_status':'self_attested_not_verified'})
            try:
                meta=json.loads(self._download(client,f'https://api.github.com/repos/{user}/{repo}',100000))
                if meta.get('private') is not False:raise WorkspaceConflict('private_repository_not_authorized')
                ref=request.ref or meta['default_branch']
                result=json.loads(self._download(client,f'https://api.github.com/repos/{user}/{repo}/commits/{quote(ref,safe="")}',200000))
                commit=result['sha']
                if not re.fullmatch(r'[a-f0-9]{40}',commit):raise WorkspaceConflict('github_commit_invalid')
            except WorkspaceConflict:raise
            except (ValueError,KeyError,TypeError) as exc:raise WorkspaceConflict('github_metadata_invalid') from exc
            raw=self._download(client,f'https://codeload.github.com/{user}/{repo}/zip/{commit}',MAX_ARCHIVE_BYTES)
            files,safety=scan_zip(raw,strip_single_root=True)
            return self.store.publish_files(owner,project_id,files,origin='github',commit_sha=commit,metadata={
                **safety,'repository_url':f'https://github.com/{user}/{repo}','license':(meta.get('license') or {}).get('spdx_id','UNKNOWN'),
                'source_ref':str(ref)[:150],'private':False,'contribution_status':'self_attested_not_verified'})
        finally:
            if not supplied:client.close()
