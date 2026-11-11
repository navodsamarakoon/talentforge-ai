"""Disposable HTTP contract receiver. No SMTP, n8n execution or production access."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    accepted = 0

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path != '/counts':
            self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(json.dumps({'accepted':Handler.accepted}).encode())

    def do_POST(self):
        assert self.path in {
            '/webhook/talentforge-cv-screening',
            '/webhook/talentforge-recruitment-automation',
        }
        assert self.headers.get('X-TalentForge-Webhook-Secret') == 'synthetic-webhook'
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert body['candidate_email'].endswith('@example.com')
        assert body['candidate_email'] != body['cv_profile']['email']
        assert body['application_id'] and body['job_id'] and body['cv_text']
        assert self.headers['Idempotency-Key'] == body['idempotency_key']
        Handler.accepted += 1
        self.send_response(202);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(b'{"accepted":true}')


if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',5678),Handler).serve_forever()
