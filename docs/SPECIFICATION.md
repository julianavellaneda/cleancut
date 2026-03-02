# Technical Specifications

## 1. Database Schema Updates (`models.py`)

| Table | Field | Type | Description |
| :--- | :--- | :--- | :--- |
| `Job` | `prompt` | `String` | The user's editing instructions. |
| `Job` | `media_type` | `String` | 'audio' or 'video'. |
| `Job` | `original_filename` | `String` | To track the extension (mp4, mov, mp3). |
| `Violation` | `label` | `String` | Generic label (e.g., "Filler Word", "Off-topic"). |
| `Violation` | `action` | `String` | Suggested action: 'cut' or 'mute'. |

## 2. API Endpoint Changes

### `POST /api/jobs`
- **Request (Multipart):**
    - `file`: The media file.
    - `prompt`: String (e.g., "Remove the part where I talk about the price").
    - `auto_scrub`: Boolean (Apply silence/filler detection).
- **Response:** Job ID and initial status.

## 3. Library Selections

- **FFmpeg (`ffmpeg-python`):** Replaces `pydub`. Essential for video container support and complex filter chains.
- **faster-whisper:** Retained for transcription. High performance on M-series chips and CPU.
- **Silero VAD:** For high-accuracy silence/voice detection.
- **OpenAI GPT-4o-mini / GPT-4o:** For semantic analysis.

## 4. Video Editing Logic (FFmpeg)

To cut a video at specific intervals `[t1, t2]` and `[t3, t4]`:

```bash
# Conceptual Filter Graph
ffmpeg -i input.mp4 -filter_complex 
"[0:v]trim=start=t1:end=t2,setpts=PTS-STARTPTS[v0]; 
 [0:a]atrim=start=t1:end=t2,asetpts=PTS-STARTPTS[a0]; 
 [0:v]trim=start=t3:end=t4,setpts=PTS-STARTPTS[v1]; 
 [0:a]atrim=start=t3:end=t4,asetpts=PTS-STARTPTS[a1]; 
 [v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" 
-map "[v]" -map "[a]" output.mp4
```

## 5. UI/UX Markers

- Markers should be color-coded:
    - **Red:** Potential Cuts (Silence/Sensitive info).
    - **Yellow:** Suggested Mutes (Background noise/Filler).
    - **Green:** Highlighted segments (Keepers).
