"""Markdown structure is not runtime proof; oversized tables/fences remain bounded fragments."""
from job_agent.knowledge.markdown_chunks import markdown_ranges
from job_agent.resume_workspace.code_parser import parse_file
from job_agent.resume_workspace.code_rag import _chunks


def chunks(text):return [c for c in _chunks('fixed-snapshot','guide.md',text,parse_file('guide.md',text)) if c.metadata['granularity']=='markdown']


def test_headings_form_source_ranges_and_fenced_fake_heading_is_not_a_section():
    text='# Guide\nIntro.\n\n## Code\n```python\n# not a heading\nprint(1)\n```\n\n## End\nDone.\n'
    result=chunks(text);assert len(result)==3
    assert result[1].text=='## Code\n```python\n# not a heading\nprint(1)\n```\n\n'
    assert not any(c.metadata['structural_fragment'] for c in result)
    assert ''.join(c.text for c in result)==text


def test_long_section_uses_paragraph_boundaries_before_hard_fragmentation():
    text='# Long\n'+'first paragraph\n'*39+'\n'+'second paragraph\n'*39+'\n'+'last paragraph\n'*10
    ranges=markdown_ranges(text);assert len(ranges)==2
    assert all(end-start+1<=80 for start,end in ranges)
    assert not any(c.metadata['structural_fragment'] for c in chunks(text))
    assert ''.join(c.text for c in chunks(text))==text


def test_oversized_fenced_block_and_table_are_marked_fragments_without_forged_quotes():
    for body in ('```text\n'+'data row\n'*100+'```\n','| column | value |\n'+'| a | b |\n'*100):
        text='# Large\n'+body;result=chunks(text)
        assert len(result)>1 and all(c.metadata['structural_fragment'] for c in result)
        assert all(c.metadata['end_line']-c.metadata['start_line']+1<=80 for c in result)
        assert ''.join(c.text for c in result)==text
        lines=text.splitlines(keepends=True)
        assert all(c.text==''.join(lines[c.metadata['start_line']-1:c.metadata['end_line']]) for c in result)


def test_flat_baseline_still_covers_original_text_without_claiming_markdown_ast():
    text='# A\na\n## B\nb\n';all_chunks=_chunks('s','guide.md',text,parse_file('guide.md',text))
    assert [c.text for c in all_chunks if c.metadata['granularity']=='flat']==[text]
    assert not any(c.metadata['granularity']=='ast' for c in all_chunks)
