import os
from PIL import Image, ImageDraw, ImageFont

def generate_icons():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dirs = [
        os.path.join(base_dir, "apps", "desktop-tauri", "icons"),
        os.path.join(base_dir, "apps", "desktop-tauri", "src-tauri", "icons")
    ]

    for d in dirs:
        os.makedirs(d, exist_ok=True)

        # Create high-res base icon (512x512) with AuraStock blue gradient and box
        img = Image.new("RGBA", (512, 512), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Rounded rectangle background
        draw.rounded_rectangle([(32, 32), (480, 480)], radius=96, fill=(14, 165, 233, 255))
        # Inner accent box
        draw.rounded_rectangle([(96, 96), (416, 416)], radius=48, fill=(3, 105, 161, 255))
        # White center 'A' or cube symbol
        draw.polygon([(256, 140), (380, 210), (380, 350), (256, 420), (132, 350), (132, 210)], fill=(255, 255, 255, 255))
        draw.polygon([(256, 160), (360, 220), (256, 280), (152, 220)], fill=(224, 242, 254, 255))
        draw.polygon([(152, 240), (246, 290), (246, 395), (152, 340)], fill=(186, 230, 253, 255))
        draw.polygon([(266, 290), (360, 240), (360, 340), (266, 395)], fill=(125, 211, 252, 255))

        # Save standard sizes
        img.resize((32, 32), Image.Resampling.LANCZOS).save(os.path.join(d, "32x32.png"))
        img.resize((128, 128), Image.Resampling.LANCZOS).save(os.path.join(d, "128x128.png"))
        img.resize((256, 256), Image.Resampling.LANCZOS).save(os.path.join(d, "128x128@2x.png"))
        img.save(os.path.join(d, "icon.png"))

        # Save multi-res ICO
        ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        img.save(os.path.join(d, "icon.ico"), sizes=ico_sizes)

        # Save dummy icns
        img.resize((128, 128)).save(os.path.join(d, "icon.icns"), format="PNG")

        print(f"[OK] Generated AuraStock icons in {d}")

if __name__ == "__main__":
    generate_icons()
