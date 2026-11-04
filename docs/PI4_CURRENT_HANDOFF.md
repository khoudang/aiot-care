# Current Pi4 integration handoff

This branch preserves the source last verified on the Pi at release `controls-fix-1cf8243bcf0b`. The Pi was subsequently shut down by the owner; publishing this branch does not contact or modify it. This is a source snapshot, not a claim of current hardware availability.

## Included
- Current `fix_ui` presentation integrated with the BLE/AI backend, retaining buzzer controls, kitchen history and patient safety confirmation.
- YOLOv3-tiny person-box horizontal tracking (one pan servo), replacing nose-based tracking. Pose remains responsible for fall detection; Hands remains for gestures.
- Bounded pan corrections: maximum 3 degrees/update and 6 degrees/second of software command budget; stale/lost targets never replay movement.
- Restored missing kitchen buzzer change handler; request IDs and ACK plus telemetry confirmation retained. Safety locks are not bypassed.
- Admin member-account creation, inline edit/delete forms and clear error messages. Duplicate usernames cannot leave a SQLite transaction open. Self-lock/delete remains prohibited.

## Runtime/dependencies
OpenCV 5 removed the Darknet importer. `requirements.txt` therefore constrains OpenCV to 4.x; this manifest compatibility constraint is the only runtime dependency-file adjustment made for publishing, not an assertion that the Pi environment was reinstalled.

The verified Pi used its existing Python 3.11 environment and an isolated OpenCV 4.11 directory:

```ini
# Effective systemd environment on the verified release
PYTHONPATH=/home/khoi/aiot-care-models/opencv4
OPENCV_FOR_THREADS_NUM=1
```

Model overrides in the Pi's private `.env`:

```dotenv
YOLO_CFG_PATH=/home/khoi/aiot-care-models/yolov3-tiny.cfg
YOLO_WEIGHTS_PATH=/home/khoi/aiot-care-models/yolov3-tiny.weights
YOLO_INPUT_SIZE=224
YOLO_INTERVAL_SEC=0.5
```

Model binaries, private `.env`, credentials, databases, session cookies and local deployment/verification dumps are intentionally not committed. `coco.names` is unnecessary: only COCO class 0 (person) is used. Model weights were obtained from the public Darknet-test mirror; the tested weights SHA256 was `dccea06f59b781ec1234ddf8d1e94b9519a97f4245748a7d4db75d5b7080a42c`.

Before configuring another Pi, inspect its actual model files, interpreter, UART wiring and effective systemd drop-ins; do not blindly overwrite its service or copy obsolete paths.

## Verification already completed
- Pan optimization: 132 Python tests passed on Pi before the admin/buzzer changes.
- Final targeted admin flow: create, duplicate rejection, lock, unlock, edit, delete and self-protection passed against temporary SQLite, not live accounts.
- Kitchen buzzer UI test passed with a fake socket; two Pi backend contract tests passed without actuator commands.
- Final deployed dashboard HTTP 200; required assets and new form/cache version verified; all three nodes connected. Persistent account/config/gesture fingerprints were preserved during deployment.
- Replay benchmark on Pi with YOLO/Pose/Hands: encoded 15 FPS; one OpenCV thread used less CPU than two. Replay is shifted versions of one public photo, NOT evidence of real-camera smoothness or detection accuracy.

## Remaining physical checks and known limitations
- Camera was left OFF and UART disabled, preserving the owner's state. No serial port was detected. Real pan motion, correct wiring/direction and camera-to-browser latency remain unverified.
- Existing fall heuristic still needs a keypoint visibility/plausible-body gate. Held gestures can repeat requests after cooldown. These were reproduced synthetically and deliberately not mixed into the admin/buzzer fix.
- The exact original live lock/delete failure was not established. Reproduced defects fixed here include log-loading errors hiding user controls and duplicate-account SQLite transaction leakage. In-page forms also avoid reliance on native account dialogs.
- Source can be published while Pi is off; physical acceptance requires an owner-supervised session later.

## Small targeted checks

```bash
node tests/test_kitchen_buzzer_ui.cjs
python -m pytest tests/test_admin_management.py::test_existing_lock_unlock_delete_and_protection tests/test_admin_management.py::test_duplicate_and_create_lock_unlock_delete_flow -q
```

Install pytest only in a development/test environment. JS admin DOM tests additionally require jsdom; pass its isolated `node_modules` directory through `NODE_PATH`, then run `node --test tests/test_admin_management_ui.cjs`. Do not import `app.py` merely to inspect routes: it starts hardware services.
