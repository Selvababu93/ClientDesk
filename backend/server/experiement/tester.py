



# @app.post("/register", response_model=RegisterResp)
# def register(req: RegisterReq, db: Session = Depends(get_db)):
#     token = gen_token()
#     dev = Device(hostname=req.hostname, os=req.os, arch=req.arch,
#                  agent_version=req.agent_version, token=token,
#                  last_seen=datetime.utcnow(), online=False)
#     db.add(dev); db.commit(); db.refresh(dev)
#     return RegisterResp(device_id=dev.id, token=token)