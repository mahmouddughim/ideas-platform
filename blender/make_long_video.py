# يحوّل حلقة Blender (10 ثوانٍ) إلى فيديو طويل (3 ساعات افتراضياً) مع أصوات الأجواء.
# يحتاج: Python 3 و FFmpeg (https://ffmpeg.org) مثبتاً ومضافاً إلى PATH.
#
# الخطوات على حاسوبك:
#   1) blender -b -P andalus_courtyard.py -- --render out/frame_
#   2) ضع ملفات أصوات (mp3 أو wav) في مجلد sounds، مثل: نافورة، صراصير ليل، عود هادئ.
#   3) python make_long_video.py --frames out --sounds sounds --hours 3 --output layla_qurtuba.mp4

import argparse
import glob
import os
import subprocess
import tempfile


def run(cmd):
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="out", help="مجلد صور الحلقة من Blender")
    ap.add_argument("--sounds", default="sounds", help="مجلد أصوات الأجواء")
    ap.add_argument("--hours", type=float, default=3.0)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--output", default="long_video.mp4")
    args = ap.parse_args()
    seconds = int(args.hours * 3600)

    with tempfile.TemporaryDirectory() as tmp:
        # 1) الصور ← مقطع قصير واحد.
        loop = os.path.join(tmp, "loop.mp4")
        run(["ffmpeg", "-y", "-framerate", str(args.fps), "-pattern_type", "glob",
             "-i", os.path.join(args.frames, "*.png"),
             "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", loop])

        # 2) الأصوات: كل ملف يتكرر طوال المدة، ثم تُمزج معاً بمستويات متوازنة.
        sounds = sorted(glob.glob(os.path.join(args.sounds, "*.mp3")) + glob.glob(os.path.join(args.sounds, "*.wav")))
        audio_inputs, filters = [], []
        for i, path in enumerate(sounds):
            audio_inputs += ["-stream_loop", "-1", "-i", path]
            filters.append(f"[{i + 1}:a]volume=0.8,aresample=48000[a{i}]")
        mix = ""
        if sounds:
            labels = "".join(f"[a{i}]" for i in range(len(sounds)))
            mix = ";".join(filters) + f";{labels}amix=inputs={len(sounds)}:normalize=0,afade=t=in:d=5,afade=t=out:st={seconds - 8}:d=8[aout]"

        # 3) تكرار الفيديو إلى المدة المطلوبة بلا إعادة ترميز للصورة.
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", loop] + audio_inputs + ["-t", str(seconds), "-map", "0:v"]
        if sounds:
            cmd += ["-filter_complex", mix, "-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-c:v", "copy", "-movflags", "+faststart", args.output]
        run(cmd)
    print("تم:", args.output)


if __name__ == "__main__":
    main()
