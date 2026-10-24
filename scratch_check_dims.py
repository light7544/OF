import os
import re
from PIL import Image

# Let's inspect the 10 order flow screenshots to see resolution and header area
sample_files = [
    "20261013_111021_order_flow.png",
    "20261013_111522_order_flow.png",
    "20261013_112020_order_flow.png",
    "20261013_112520_order_flow.png",
    "20261013_113019_order_flow.png",
    "20261013_113520_order_flow.png",
    "20261013_114019_order_flow.png",
    "20261013_114519_order_flow.png",
    "20261013_115020_order_flow.png",
    "20261013_115523_order_flow.png",
]

for f in sample_files:
    p = os.path.join("screenshots", "footprint", f)
    im = Image.open(p)
    print(f"{f}: size={im.size}, mode={im.mode}")
