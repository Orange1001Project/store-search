import pandas as pd
LABELS={'store_name':'가맹점명','market_name':'시장명','market_type':'시장유형','item_text':'취급품목'}

def build_search_text(row,fields):
    ps=[]
    for f in fields:
        v=row.get(f)
        if v is None or pd.isna(v) or str(v).strip()=='': continue
        ps.append(f"{LABELS.get(f,f)}: {str(v).strip()}")
    return ' / '.join(ps)

def attach_templates(df,templates):
    out=df.copy()
    for name,spec in templates.items():
        out[f'search_text_{name}']=out.apply(lambda row:build_search_text(row,spec['fields']),axis=1)
    return out
