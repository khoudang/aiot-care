# Run camera AI on Windows

Use Python 3.10 or 3.11 with the project's virtual environment. The camera code
uses MediaPipe's legacy `solutions` API; the versions in `requirements.txt`
preserve that API and avoid installing two distributions that both provide `cv2`.

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe app.py
```

Stop any previous server before starting this one. A plain `python app.py` can
use a different, incompatible global environment unless `.venv` is activated.

To check Pose and Hands without opening a camera:

```powershell
.\.venv\Scripts\python.exe -c "import mediapipe as mp; p=mp.solutions.pose.Pose(); h=mp.solutions.hands.Hands(); print('Pose and Hands OK'); p.close(); h.close()"
```

Model startup does not verify camera access, gesture accuracy, fall detection,
or servo wiring. Check those separately on the actual hardware. The UART servo
also needs the correct Windows COM port or the gateway's serial device path.
