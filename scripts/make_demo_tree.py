"""Create a realistic-looking demo folder for screenshots and manual testing.

Uses sparse files, so it "looks" like hundreds of GB without using real disk space.
    python scripts/make_demo_tree.py demo
"""

import os
import random
import sys
import time

GB = 1024**3
MB = 1024**2

LAYOUT = {
    "Users/Alex/Videos/Holiday 2024": [("Beach day.mp4", 3.8 * GB), ("Sunset timelapse.mov", 2.1 * GB),
                                       ("Drone flight.mp4", 1.6 * GB), ("Kids pool.mp4", 900 * MB)],
    "Users/Alex/Videos/OBS Recordings": [(f"2025-0{i} gameplay.mkv", (4 + i) * GB) for i in range(1, 6)],
    "Users/Alex/Pictures/Camera Roll": [(f"IMG_{4000 + i}.jpg", random.randint(2, 7) * MB) for i in range(160)],
    "Users/Alex/Pictures/RAW": [(f"DSC_{1000 + i}.nef", 28 * MB) for i in range(90)],
    "Users/Alex/Music/Library": [(f"Track {i:02d}.flac", random.randint(25, 60) * MB) for i in range(80)],
    "Users/Alex/Documents/Work": [("Quarterly report.pdf", 14 * MB), ("Budget.xlsx", 2 * MB),
                                  ("Mail archive.pst", 3.2 * GB), ("Presentation.pptx", 85 * MB)],
    "Users/Alex/Downloads": [("Win11_23H2.iso", 6.2 * GB), ("ubuntu-24.04-desktop.iso", 5.7 * GB),
                             ("SteamSetup.exe", 2 * MB), ("driver_package.zip", 780 * MB),
                             ("old-backup.7z", 12.5 * GB), ("VSCodeSetup.exe", 95 * MB)],
    "Users/Alex/AppData/Local/Temp": [(f"tmp{i:04x}.tmp", random.randint(1, 80) * MB) for i in range(40)],
    "Users/Alex/AppData/Local/Google/Chrome/User Data/Default/Cache": [
        (f"f_{i:06x}", random.randint(1, 9) * MB) for i in range(120)],
    "Users/Alex/AppData/Roaming/Discord/Cache": [(f"data_{i}", 40 * MB) for i in range(12)],
    "Games/SteamLibrary/steamapps/common/Cyber Odyssey": [("game.pak", 58 * GB), ("game_hd_textures.pak", 21 * GB),
                                                          ("Odyssey.exe", 210 * MB)],
    "Games/SteamLibrary/steamapps/common/Racing Legends": [("data0.bin", 31 * GB), ("RacingLegends.exe", 120 * MB)],
    "Games/SteamLibrary/steamapps/shadercache": [(f"cache_{i}.bin", 300 * MB) for i in range(10)],
    "Program Files/Adobe/Photoshop": [("Photoshop.exe", 280 * MB), ("resources.dat", 2.6 * GB)],
    "Program Files/Microsoft Office/root": [(f"lib{i}.dll", 45 * MB) for i in range(40)],
    "Windows/System32": [(f"sys{i}.dll", random.randint(1, 30) * MB) for i in range(200)],
    "Windows/WinSxS": [(f"pkg_{i}.cab", 120 * MB) for i in range(60)],
    "Windows/SoftwareDistribution/Download": [("update_kb503.msu", 1.4 * GB)],
    "Projects/website/node_modules": [(f"pkg{i}.js", random.randint(1, 4) * MB) for i in range(150)],
    "Projects/ml-experiments/checkpoints": [("epoch_10.pt", 4.4 * GB), ("epoch_20.pt", 4.4 * GB)],
    "": [("pagefile.sys", 16 * GB), ("hiberfil.sys", 6.4 * GB)],
}


def main(target: str) -> None:
    random.seed(7)
    for folder, files in LAYOUT.items():
        d = os.path.join(target, *folder.split("/")) if folder else target
        os.makedirs(d, exist_ok=True)
        for name, size in files:
            path = os.path.join(d, name)
            with open(path, "wb") as f:
                f.truncate(int(size))
            age = random.uniform(2, 900) * 86400
            ts = time.time() - age
            os.utime(path, (ts, ts))
    print(f"Demo tree written to {os.path.abspath(target)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo")
