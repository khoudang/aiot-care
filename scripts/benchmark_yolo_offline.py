"""Offline DNN input-size comparison on synthetic shifts of one real image.
No VideoCapture, app import, UART, GPIO, network service restart or live config edits.
This measures timing and detection retention, NOT accuracy on real video.
"""
import cv2,numpy as np,time,json,statistics
cv2.setNumThreads(1)
root='/home/khoi/aiot-care-models/'
img=cv2.imread(root+'person.jpg');h,w=img.shape[:2]
frames=[cv2.warpAffine(img,np.float32([[1,0,dx],[0,1,0]]),(w,h)) for dx in [0,-32,32,0]]
net=cv2.dnn.readNet(root+'yolov3-tiny.weights',root+'yolov3-tiny.cfg');layers=net.getUnconnectedOutLayersNames();report=[]
for size in [160,192,224,320]:
 costs=[];hits=[]
 for i,frame in enumerate([frames[0]]+frames*2):
  start=time.perf_counter();net.setInput(cv2.dnn.blobFromImage(frame,1/255.,(size,size),swapRB=True));outs=net.forward(layers);ms=(time.perf_counter()-start)*1000
  scores=[float(row[4]*row[5]) for out in outs for row in out if int(np.argmax(row[5:]))==0]
  if i:costs.append(ms);hits.append(max(scores,default=0.))
 report.append({'input_size':size,'warm_median_ms':round(statistics.median(costs),2),'warm_max_ms':round(max(costs),2),'passes_confidence_0_5':sum(x>=.5 for x in hits),'samples':len(hits),'minimum_max_person_confidence':round(min(hits),3)})
print(json.dumps({'opencv':cv2.__version__,'threads':cv2.getNumThreads(),'data':'one darknet person.jpg with synthetic horizontal shifts, repeated twice','results':report}))
