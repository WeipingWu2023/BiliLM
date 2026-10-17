"""Deterministic scorer. Insertions are error proxies, not proof of semantic hallucination."""
import re
import unicodedata


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text).lower() if not unicodedata.category(c).startswith(('P','Z')) and not c.isspace())


def distance(reference,hypothesis):
    # Edit distance + deterministic S/D/I counts. Substitution wins tied paths.
    previous = [(i,0,i,0) for i in range(len(hypothesis)+1)]
    for ri,r in enumerate(reference,1):
        current = [(ri,0,0,ri)]
        for hi,h in enumerate(hypothesis,1):
            if r==h:
                current.append(previous[hi-1])
            else:
                d,s,i,deleted=previous[hi-1]
                substitution=(d+1,s+1,i,deleted)
                d,s,i,deleted=previous[hi]
                deletion=(d+1,s,i,deleted+1)
                d,s,i,deleted=current[hi-1]
                insertion=(d+1,s,i+1,deleted)
                current.append(min((substitution,deletion,insertion),key=lambda x:x[0]))
        previous=current
    d,s,i,deleted=previous[-1]
    return {'distance':d,'substitutions':s,'insertions':i,'deletions':deleted,'reference_units':len(reference),'rate':d/len(reference) if reference else None}


def score(reference,segments,terms=(),reference_segments=(),silence_intervals=()):
    predicted=' '.join(s['text'] for s in segments)
    cer=distance(list(normalize(reference)),list(normalize(predicted)))
    # Whitespace-based WER is not appropriate for unsegmented Chinese.
    english_ref=re.findall(r"[a-z]+(?:['-][a-z]+)*|\d+",reference.lower())
    english_hyp=re.findall(r"[a-z]+(?:['-][a-z]+)*|\d+",predicted.lower())
    terminology=[]
    for term in terms:
        if not normalize(term):
            continue
        wanted=normalize(reference).count(normalize(term)); got=normalize(predicted).count(normalize(term))
        terminology.append({'term':term,'reference_count':wanted,'prediction_count':got,'matched_count':min(wanted,got),'missing_count':max(0,wanted-got),'extra_count':max(0,got-wanted)})
    boundaries=[]; omissions=[]
    for ref in reference_segments:
        overlapping=[s for s in segments if min(ref['end'],s['end'])>max(ref['start'],s['start'])]
        if not overlapping:
            omissions.append(ref)
        else:
            boundaries.append({'start_error_seconds':abs(min(s['start'] for s in overlapping)-ref['start']),
                               'end_error_seconds':abs(max(s['end'] for s in overlapping)-ref['end'])})
    duplicate_pairs=[i for i in range(1,len(segments)) if normalize(segments[i]['text'])==normalize(segments[i-1]['text']) and normalize(segments[i]['text'])]
    overlaps=[i for i in range(1,len(segments)) if segments[i]['start']<segments[i-1]['end']]
    silent_output=[i for i,s in enumerate(segments) if any(s['start']>=a and s['end']<=b for a,b in silence_intervals) and normalize(s['text'])]
    term_reference=sum(t['reference_count'] for t in terminology)
    term_prediction=sum(t['prediction_count'] for t in terminology)
    term_matched=sum(t['matched_count'] for t in terminology)
    return {'cer':cer,'english_wer':distance(english_ref,english_hyp) if english_ref else None,
            'wer_policy':'English tokens only; no guessed Chinese word segmentation',
            'terms':terminology,'term_recall':term_matched/term_reference if term_reference else None,
            'term_precision':term_matched/term_prediction if term_prediction else None,
            'timestamp_errors':boundaries or None,
            'timestamp_mae_seconds':sum(t['start_error_seconds']+t['end_error_seconds'] for t in boundaries)/(2*len(boundaries)) if boundaries else None,
            'missing_reference_segments':omissions,
            'adjacent_duplicate_candidates':duplicate_pairs,'overlap_candidates':overlaps,
            'speech_in_verified_silence_candidates':silent_output,'semantic_hallucinations':'requires separate human audio review; CER insertions are not verified hallucinations'}


def disagreements(first,second):
    if not first['metrics'].get('source_audio_sha256') or first['metrics'].get('source_audio_sha256')!=second['metrics'].get('source_audio_sha256'):
        raise ValueError('需要同一原音频 SHA256 的两个 run，不能比较未知来源')
    differences=[]
    for i,s in enumerate(first['raw']):
        neighbors=[r for r in second['raw'] if min(s['end'],r['end'])>max(s['start'],r['start'])]
        other=' '.join(r['text'] for r in neighbors)
        if normalize(s['text'])!=normalize(other):
            differences.append({'index':i,'start':s['start'],'end':s['end'],'primary':s['text'],'secondary':other,'uncertain':True})
    return {'differences':differences,'verified':False,'policy':'重叠时间窗候选差异；不同切段也会产生候选，需要重听'}
