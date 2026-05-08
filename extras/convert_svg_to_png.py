import os
from cairosvg import svg2png
from PIL import Image

input_folder = 'newlogos'
output_folder = 'newlogos/pngs'
os.makedirs(output_folder, exist_ok=True)

for filename in os.listdir(input_folder):
    if filename.lower().endswith('.svg'):
        svg_path = os.path.join(input_folder, filename)
        png_path = os.path.join(output_folder, filename[:-4] + '.png')
        # Convert SVG to PNG
        svg2png(url=svg_path, write_to=png_path)
        # Ensure PNG is RGBA (transparent)
        img = Image.open(png_path).convert('RGBA')
        img.save(png_path)
print('Conversion complete!')
