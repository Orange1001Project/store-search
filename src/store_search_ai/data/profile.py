import pandas as pd

def profile_frame(df,source):
    r={'source':source,'rows':int(len(df)),'columns':list(df.columns),'null_count':{c:int(df[c].isna().sum()) for c in df.columns},'null_rate':{c:round(float(df[c].isna().mean()),6) for c in df.columns},'unique_count':{c:int(df[c].nunique(dropna=True)) for c in df.columns}}
    if '사업자번호' in df.columns:
        s=df['사업자번호'].astype('string').str.replace(r'\D+','',regex=True); r['business_no_duplicate_rows']=int(s.duplicated(keep=False).sum())
    if '가맹점번호' in df.columns:
        s=df['가맹점번호'].astype('string').str.strip(); r['merchant_no_missing']=int((s.isna()|(s=='')).sum())
    if '취급품목' in df.columns:
        s=df['취급품목'].astype('string').str.strip(); m=s.isna()|(s==''); r['item_missing_rows']=int(m.sum()); r['item_missing_rate']=round(float(m.mean()),6); r['top_items']=s[~m].value_counts().head(50).to_dict()
    if '시장분류코드' in df.columns:
        r['market_type_counts']=df['시장분류코드'].astype('string').str.strip().value_counts(dropna=False).to_dict()
    return r
