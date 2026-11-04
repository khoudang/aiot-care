"""Pi replay benchmark: synthetic shifts of one photo, NOT live-camera acceptance.
No app import, camera, UART, GPIO, BLE or actuator calls.
"""
import cv2,mediapipe as mp,numpy as np,threading,time,json,statistics,resource
from person_tracker import PersonTracker,bounded_pan_step
from config import YOLO_CFG_PATH,YOLO_WEIGHTS_PATH
photo=cv2.imread('/home/khoi/aiot-care-models/person.jpg');h,w=photo.shape[:2]
frames=[cv2.warpAffine(photo,np.float32([[1,0,dx],[0,1,0]]),(w,h)) for dx in [-16,0,16,0]]
results=[]
for threads in [1,2]:
 cv2.setNumThreads(threads)
 tracker=PersonTracker(YOLO_CFG_PATH,YOLO_WEIGHTS_PATH,cv=cv2)
 pose=mp.solutions.pose.Pose(model_complexity=0);hands=mp.solutions.hands.Hands(model_complexity=0,max_num_hands=2)
 # Warm actual models before measuring.
 tracker.process(frames[0]);rgb=cv2.cvtColor(frames[0],cv2.COLOR_BGR2RGB);pose.process(rgb);hands.process(rgb)
 lock=threading.Lock();slot={'frame':None,'ts':0.,'gen':0};stop=threading.Event();works=[];yolos=[];enc_times=[];errors=[];angles=[];skips=[]
 def ai():
  last=0;cycle=0;angle=90.;prev=None
  try:
   while not stop.is_set():
    with lock:frame,ts,g=slot['frame'],slot['ts'],slot['gen']
    if g==last or frame is None:time.sleep(.002);continue
    skips.append(max(0,g-last-1));last=g;cycle+=1;started=time.perf_counter();before=tracker.last_run;x=tracker.process(frame)
    if tracker.last_run!=before:yolos.append(tracker.work_ms)
    scaled=cv2.resize(frame,(320,240));rgb=cv2.cvtColor(scaled,cv2.COLOR_BGR2RGB);pose.process(rgb)
    if cycle%3==0:hands.process(rgb)
    end=time.perf_counter();works.append((end-started)*1000)
    if x is not None and end-ts<=.8:
     nxt=bounded_pan_step(x,w,angle,.5 if prev is None else end-prev,kp=.06,smoothing=.35,deadzone=24,minimum=0,maximum=180,invert=False);prev=end
     if nxt is not None:angles.append(abs(nxt-angle));angle=nxt
  except Exception as e:errors.append(repr(e));stop.set()
 worker=threading.Thread(target=ai);usage=resource.getrusage(resource.RUSAGE_SELF);cpu0=usage.ru_utime+usage.ru_stime;t0=time.perf_counter();worker.start();count=0;next_frame=t0
 while time.perf_counter()-t0<12 and not stop.is_set():
  now=time.perf_counter()
  if now<next_frame:time.sleep(next_frame-now)
  frame=frames[count%len(frames)];captured=time.perf_counter()
  with lock:slot.update(frame=frame,ts=captured,gen=count+1)
  ok,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,65]);assert ok
  enc_times.append(time.perf_counter());count+=1;next_frame=t0+count/15
 stop.set();worker.join(timeout=10);assert not worker.is_alive();elapsed=time.perf_counter()-t0;u=resource.getrusage(resource.RUSAGE_SELF);cpu=u.ru_utime+u.ru_stime-cpu0
 pose.close();hands.close();intervals=[(b-a)*1000 for a,b in zip(enc_times,enc_times[1:])]
 results.append({'opencv_threads':threads,'duration_sec':round(elapsed,2),'encoded_fps':round((len(enc_times)-1)/(enc_times[-1]-enc_times[0]),2),'encoded_interval_p95_ms':round(sorted(intervals)[int(.95*(len(intervals)-1))],1),'ai_cycles':len(works),'ai_work_median_ms':round(statistics.median(works),1),'yolo_calls':len(yolos),'yolo_work_median_ms':round(statistics.median(yolos),1),'process_cpu_one_core_percent':round(cpu/elapsed*100,1),'max_simulated_pan_step':round(max(angles,default=0),2),'dropped_old_frames':sum(skips),'errors':errors})
print(json.dumps({'data':'one public photo, synthetic shifts, replay source 15fps; not a camera or streamed-browser test','results':results}))
