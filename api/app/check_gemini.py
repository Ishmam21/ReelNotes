"""Run explicit, small Gemini diagnostics; never connects to PostgreSQL."""
import importlib.metadata
import os
from unittest.mock import patch
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from app import db  # Load api/.env, without opening a connection.
from app.guide import Extraction, Consolidation, provider_schema, extract_claims, build_snapshot, generate_guide

class Minimal(BaseModel):
    answer: str

class Captured(Exception):
    pass

def main():
    for package in ('langchain-google-genai', 'langchain-core', 'google-genai', 'pydantic'):
        print(package, importlib.metadata.version(package), flush=True)
    model = os.getenv('GEMINI_MODEL')
    if not model or not os.getenv('GOOGLE_API_KEY'):
        raise SystemExit('Configure GOOGLE_API_KEY and GEMINI_MODEL in api/.env.')
    llm = ChatGoogleGenerativeAI(model=model, timeout=10, max_retries=0, max_tokens=16000)
    cases = [('plain LangChain', None, 'Say OK.'),
             ('minimal structured', Minimal, 'Return answer OK.'),
             ('original Extraction', Extraction, 'Return claims as an empty array.'),
             ('original Consolidation', Consolidation, 'Return a topic title, brief scope, and empty groups and exclusions arrays.'),
             ('simplified Extraction', provider_schema(Extraction), 'Return claims as an empty array.'),
             ('simplified Consolidation', provider_schema(Consolidation), 'Return a topic title, brief scope, and empty groups and exclusions arrays.')]
    succeeded = set()
    for label, schema, prompt in cases:
        runnable = llm if schema is None else llm.with_structured_output(schema, method='json_schema', include_raw=True)
        def capture(**request):
            config=request['config'].model_dump(exclude_none=True)
            # Only generation settings and schemas; no headers, keys or user data.
            print(label, 'request config:', config, flush=True)
            raise Captured()
        with patch.object(llm.client.models, 'generate_content', side_effect=capture):
            try: runnable.invoke(prompt)
            except Captured: pass
        try:
            result = runnable.invoke(prompt)
            if isinstance(result, dict) and result.get('parsing_error'):
                raise ValueError('Structured response parsing failed')
            if schema is not None:
                validator = schema if isinstance(schema, type) else (Extraction if label.endswith('Extraction') else Consolidation)
                validator.model_validate(result['parsed'])
            print(label, 'PASS (locally validated)' if schema is not None else 'PASS', flush=True)
            succeeded.add(label)
        except Exception as error:
            message=str(error).replace(os.environ['GOOGLE_API_KEY'], '[REDACTED]')
            print(label, 'FAIL', type(error).__name__, message[:2000], flush=True)
    if not {'simplified Extraction', 'simplified Consolidation'} <= succeeded:
        raise SystemExit('Live pipeline verification skipped: simplified schema probes failed.')
    segments = [{'id':'s001','start_ms':0,'end_ms':4000,
                 'text':'When multiple users can book the same seat for an event, enforce a unique constraint on event and seat in PostgreSQL.'}]
    claims = extract_claims('Database integrity', segments)
    if not claims:
        raise SystemExit('FAIL: expected actionable advice from sample.')
    snapshot = build_snapshot('PostgreSQL integrity', [dict(video_id='sample',position=1,title='Authored sample',
        source_url='https://www.instagram.com/reel/AUTHORED_SAMPLE/',segments=segments,claims=claims)])
    result, markdown = generate_guide(snapshot)
    if not result['groups'] or 'http' in markdown or '[V1 ' in markdown:
        raise SystemExit('FAIL: expected a clean instruction group from sample.')
    print('PASS: actual extraction + consolidation + agent Markdown with internal evidence references (authored sample, not live Instagram).')
    print(markdown)

if __name__ == '__main__':
    main()
