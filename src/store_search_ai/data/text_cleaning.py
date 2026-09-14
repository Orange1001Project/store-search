import html,re,pandas as pd
HTML_BREAK_RE=re.compile(r'<\s*br\s*/?\s*>',re.I)
SPACE_RE=re.compile(r'\s+')
PAREN_TOKEN_RE=re.compile(r'\([^)]{1,50}\)')

def normalize_spaces(v):
    if v is None or pd.isna(v): return None
    s=html.unescape(str(v)).replace('\xa0',' ')
    s=SPACE_RE.sub(' ',s).strip()
    return s or None

def clean_address(v):
    if v is None or pd.isna(v): return None,{'address_had_html_break':False,'address_had_nbsp':False,'address_repeated_parenthetical':False}
    raw=str(v); h=bool(HTML_BREAK_RE.search(raw)); n=('\xa0' in raw or '&nbsp;' in raw.lower())
    s=html.unescape(raw).replace('\xa0',' '); s=HTML_BREAK_RE.sub(' ',s); s=SPACE_RE.sub(' ',s).strip()
    ps=PAREN_TOKEN_RE.findall(s); r=len(ps)!=len(set(ps))
    return s or None,{'address_had_html_break':h,'address_had_nbsp':n,'address_repeated_parenthetical':r}

def clean_digits(v):
    s=normalize_spaces(v)
    if s is None: return None
    d=re.sub(r'\D+','',s)
    return d or None

def normalize_yn(v):
    s=normalize_spaces(v)
    if s is None: return pd.NA
    if s.upper()=='Y': return True
    if s.upper()=='N': return False
    return pd.NA
