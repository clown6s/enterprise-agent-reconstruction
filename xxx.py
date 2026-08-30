import os, json
from dotenv import load_dotenv; load_dotenv()
from elasticsearch import Elasticsearch
es=Elasticsearch(os.getenv("ES_HOST"), basic_auth=(os.getenv("ES_USERNAME"),os.getenv("ES_PASSWORD")),
    ssl_assert_fingerprint=os.getenv("CERT_FINGERPRINT"), request_timeout=15)
r=es.synonyms.get_synonym(id="enterprise-retrieval-synonyms")
body=r.body if hasattr(r,"body") else dict(r)
print("rules count:", len(body.get("synonyms_set",[])))
for s in body.get("synonyms_set",[]): print(s)
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe ./xxx.py; rm -f ./xxx.py
