"""Contiguous heading/paragraph ranges; oversized logical blocks stay explicit fragments."""
import re


def _fence(line,current):
    match=re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$',line)
    if not match:return current
    marker=match[1]
    if current is None:return marker
    if marker[0]==current[0] and len(marker)>=len(current) and not match[2].strip():return None
    return current


def markdown_ranges(text,*,max_lines=80,max_chars=12000):
    """1-based inclusive ranges. Never invent prefixes or split inside a fence to find a heading."""
    lines=text.splitlines(keepends=True)
    if not lines:return []
    starts=[0];fence=None
    for i,line in enumerate(lines):
        if fence is None and i and re.match(r'^\s{0,3}#{1,6}\s+',line):starts.append(i)
        fence=_fence(line,fence)
    sections=list(zip(starts,[*starts[1:],len(lines)]));result=[]
    for start,end in sections:
        if end-start<=max_lines and sum(map(len,lines[start:end]))<=max_chars:
            result.append((start+1,end));continue
        # Blank lines separate paragraphs/tables/fences, except inside code blocks.
        units=[];unit=start;fence=None
        for i in range(start,end):
            fence=_fence(lines[i],fence)
            if fence is None and not lines[i].strip():
                units.append((unit,i+1));unit=i+1
        if unit<end:units.append((unit,end))
        grouped_start=None;grouped_end=None;chars=0
        for a,b in units:
            size=sum(map(len,lines[a:b]))
            if grouped_start is not None and (b-grouped_start>max_lines or chars+size>max_chars):
                result.append((grouped_start+1,grouped_end));grouped_start=None;chars=0
            if grouped_start is None:grouped_start=a
            grouped_end=b;chars+=size
        if grouped_start is not None:result.append((grouped_start+1,grouped_end))
    return result
