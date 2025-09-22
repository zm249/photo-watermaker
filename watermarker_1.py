import os
from PIL import Image, ImageDraw, ImageFont
import piexif


def get_image_exif_date(image_path):
    """提取图片的EXIF拍摄时间"""
    exif_dict = piexif.load(image_path)
    try:
        # 获取拍摄时间（EXIF的DateTime字段）
        date_time = exif_dict['0th'][piexif.ImageIFD.DateTime].decode('utf-8')
        # 格式为 "YYYY:MM:DD HH:MM:SS"，提取年月日
        date = date_time.split(' ')[0]
        return date.replace(":", "-")  # 格式为 "YYYY-MM-DD"
    except (KeyError, ValueError):
        print("无法获取EXIF信息中的拍摄时间。")
        return None


def add_watermark(image_path, watermark_text, font_size=30, font_color=(255, 255, 255), position="center"):
    """将水印添加到图片中并保存"""
    # 打开图片
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)

    # 设置字体和字体大小
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except IOError:
        font = ImageFont.load_default()

    # 获取图片的大小
    img_width, img_height = img.size

    # 获取水印文本的大小（通过文本边界框）
    bbox = draw.textbbox((0, 0), watermark_text, font=font)
    text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # 计算水印的位置
    if position == "top_left":
        position = (10, 10)
    elif position == "top_center":
        position = ((img_width - text_width) / 2, 10)
    elif position == "top_right":
        position = (img_width - text_width - 10, 10)
    elif position == "center":
        position = ((img_width - text_width) / 2, (img_height - text_height) / 2)
    elif position == "bottom_left":
        position = (10, img_height - text_height - 10)
    elif position == "bottom_center":
        position = ((img_width - text_width) / 2, img_height - text_height - 10)
    elif position == "bottom_right":
        position = (img_width - text_width - 10, img_height - text_height - 10)
    elif position == "left_center":
        position = (10, (img_height - text_height) / 2)
    elif position == "right_center":
        position = (img_width - text_width - 10, (img_height - text_height) / 2)
    else:
        print("未知位置，使用默认位置: center")
        position = ((img_width - text_width) / 2, (img_height - text_height) / 2)

    # 添加水印
    draw.text(position, watermark_text, fill=font_color, font=font)

    # 获取目录路径和创建新目录
    dir_path = os.path.dirname(image_path)
    new_dir = os.path.join(dir_path, "_watermark")
    if not os.path.exists(new_dir):
        os.makedirs(new_dir)

    # 保存新图片
    base_name = os.path.basename(image_path)
    new_image_path = os.path.join(new_dir, f"watermarked_{base_name}")
    img.save(new_image_path)

    print(f"水印已添加并保存为: {new_image_path}")


def main():
    # 用户输入图片路径
    image_path = input("请输入图片文件路径：").strip()

    # 提取拍摄时间
    watermark_text = get_image_exif_date(image_path)
    if not watermark_text:
        print("未能获取拍摄时间，无法生成水印。")
        return

    print(f"提取的拍摄时间为：{watermark_text}")

    # 获取用户设置
    font_size = int(input("请输入字体大小（例如：30）："))
    font_color = input("请输入字体颜色（R,G,B,例如：255,255,255）：")
    font_color = tuple(map(int, font_color.split(',')))
    position = input("请输入水印位置（top_left, center, bottom_right）：").strip()

    # 添加水印
    add_watermark(image_path, watermark_text, font_size, font_color, position)


if __name__ == "__main__":
    main()
