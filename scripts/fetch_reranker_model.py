"""Download a fixed public checkpoint; never sends project material or uses inference APIs."""
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic
from urllib.request import urlopen, Request

ROOT=Path(__file__).resolve().parents[1]
REPO='cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
REVISION='1427fd652930e4ba29e8149678df786c240d8825'
WEIGHT_SHA='5daeca2481a76b5976a2bdc32f0a78532b6716da4f8cd3ff59460ef8d2f359b4'
FILES=('config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json',
       'sentencepiece.bpe.model','README.md','model.safetensors')


def main():
    dest=ROOT/'output/models/mmarco-mMiniLMv2-L12-H384-v1';dest.mkdir(parents=True,exist_ok=True)
    rows=[];started=monotonic();total=0
    for name in FILES:
        path=dest/name
        if path.is_file():
            digest=sha256(path.read_bytes()).hexdigest()
            if name=='model.safetensors' and digest!=WEIGHT_SHA:raise ValueError('existing_weight_hash_mismatch')
            rows.append({'name':name,'sha256':digest,'bytes':path.stat().st_size});continue
        url=f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}'
        temporary=dest/(name+'.partial');digest=sha256();size=0;last=0
        print('fetch '+name,flush=True)
        with urlopen(Request(url,headers={'User-Agent':'JobAgent-local-checkpoint-fetch/1'}),timeout=30) as response,temporary.open('wb') as stream:
            for block in iter(lambda:response.read(1024*1024),b''):
                size+=len(block);total+=len(block)
                if total>600*1024*1024 or monotonic()-started>900:raise RuntimeError('model_download_budget_exceeded')
                digest.update(block);stream.write(block)
                if size-last>=32*1024*1024:print(f'{name}: {size//(1024*1024)} MiB',flush=True);last=size
        if name=='model.safetensors' and digest.hexdigest()!=WEIGHT_SHA:raise ValueError('official_weight_sha256_mismatch')
        temporary.replace(path)
        rows.append({'name':name,'sha256':digest.hexdigest(),'bytes':size})
    (dest/'download-manifest.json').write_text(json.dumps({'repo':REPO,'revision':REVISION,'weight_sha256_official':WEIGHT_SHA,
        'files':rows,'external_inference_calls':0},indent=2),encoding='utf-8')
    print(json.dumps({'directory':str(dest),'files':len(rows),'bytes':sum(r['bytes'] for r in rows)}),flush=True)


if __name__=='__main__':main()
