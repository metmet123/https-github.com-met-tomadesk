from __future__ import annotations
import json
import queue
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY=16*1024*1024


class Request:
    def __init__(self,path,body,token,address):
        self.path=path; self.body=body; self.token=token; self.address=address
        self.done=threading.Event(); self.result=(503,{'error':'PC가 응답하지 않습니다. 다시 동기화하세요.'})
        self.cancelled=False


class BridgeServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,cert,key):
        self.requests=queue.Queue(maxsize=16)
        super().__init__(address,Handler)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert,key)
        self.context=context
    def get_request(self):
        conn,addr=self.socket.accept(); conn.settimeout(15)
        try: return self.context.wrap_socket(conn,server_side=True),addr
        except Exception:
            conn.close(); raise


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass  # Never log passwords, tokens or document bodies.
    def do_POST(self):
        try:
            if self.path not in ('/login','/sync','/logout'):
                self.reply(404,{'error':'경로를 찾을 수 없습니다.'}); return
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('지원하지 않는 전송 형식입니다.')
            length=int(self.headers.get('Content-Length','0'))
            if length<2 or length>MAX_BODY: raise ValueError('요청 크기를 확인하세요.')
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict): raise ValueError('잘못된 요청입니다.')
            request=Request(self.path,body,self.headers.get('Authorization','').removeprefix('Bearer '),self.client_address[0])
            self.server.requests.put_nowait(request)
            if not request.done.wait(45): request.cancelled=True
            self.reply(*request.result)
        except (ValueError,KeyError): self.reply(400,{'error':'잘못된 요청입니다.'})
        except queue.Full: self.reply(503,{'error':'PC가 사용 중입니다. 잠시 후 다시 시도하세요.'})
        except (OSError,TimeoutError): pass
    def reply(self,status,body):
        data=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store')
        self.end_headers(); self.wfile.write(data)


def dispatch(request,auth,service):
    if request.cancelled: return
    try:
        b=request.body
        if request.path=='/login':
            if len(str(b.get('password','')))>256: raise PermissionError('로그인 정보가 잘못되었습니다.')
            result={'token':auth.login(b.get('username',''),b.get('password',''),b.get('device','Android'),request.address)}
        else:
            if not auth.verify(request.token): raise PermissionError('로그인이 필요합니다.')
            if request.path=='/logout': auth.revoke(request.token); result={'ok':True}
            else:
                if b.get('server_id') and b['server_id'] != service.store.device_id:
                    raise ValueError('PC 데이터 저장소가 변경되었습니다. 동기화를 중단했습니다.')
                changes=b.get('changes',[])
                if not isinstance(changes,list) or len(changes)>100: raise ValueError('동기화 요청이 너무 큽니다.')
                results=[service.apply(c) for c in changes]
                result=service.snapshot(); result['results']=results
        request.result=(200,result)
    except PermissionError as e: request.result=(401,{'error':str(e)})
    except (ValueError,KeyError,TypeError) as e: request.result=(400,{'error':str(e)})
    except Exception: request.result=(500,{'error':'PC 동기화 처리에 실패했습니다. 모바일 변경은 유지됩니다.'})
    finally: request.done.set()
