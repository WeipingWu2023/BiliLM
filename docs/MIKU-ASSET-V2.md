# 初音未来透明学习伙伴素材 v2

- 最终资源：`frontend/public/images/miku-learning-v2.png`
- 尺寸：1254 × 1254 PNG，包含真实 alpha 通道。
- 生成方式：内置 `image_gen`，参考旧的 `miku-learning.png` 编辑；未使用脚本抠图、裁切或重绘。
- 原资源保留，可回退。
- 修改目的：补齐原图被矩形画布截断的双马尾和身体轮廓；全身自然收尾；移除背景与外围光晕。页面应使用透明背景及 `object-fit: contain`，避免容器裁切。

## 视觉检查

最终版本保留 turquoise 双马尾、蓝色笔记本、wink 和剪刀手、灰色上衣/青色领带及黑色袖套。全身、鞋与发梢均可见，外围没有矩形底色；不包含文字。图像四边留有透明空隙，未人为给图像添加遮挡层。

像素检查：`Format32bppArgb`；1,043,074 个完全透明像素；527,812 个半透明像素；1,630 个不透明像素。非透明内容边界为 `(65, 44)` 至 `(1227, 1223)`，没有内容触及画布边缘。透明度检查仅用于验证文件，没有改写图像。

## 生成提示词

首次编辑产生全身版本，但仍有光晕，未用于页面：

```text
Use case: background-extraction / identity-preserve.
Asset type: transparent web illustration for a Chinese video-learning notebook, BiliLM.
Edit target: the supplied original Hatsune Miku PNG. Preserve her polished cheerful 2D anime cel-shaded identity and palette: turquoise twin tails with dark magenta-accent hair clips, turquoise eyes, happy wink, gray sleeveless collared top with teal tie, black detached sleeves with teal cuffs, modest black pleated skirt, dark thigh-high stockings, and blue notebook held against the torso. One hand makes a friendly peace sign.
Primary request: Redraw/outpaint the framing into a COMPLETE FULL-BODY character illustration with natural freely flowing twin tails, including ALL hair tips, hands, fingers, clothes, legs, shoes and accessories. The complete figure must sit comfortably INSIDE the canvas with approximately 10% genuinely transparent empty margin on every side. Natural lively standing pose, feet fully visible. Keep clear facial detail, warm friendly learning companion mood.
Scene/backdrop: ACTUAL TRANSPARENT ALPHA, no background at all, empty transparency around and between the hair strands and limbs.
Composition/framing: portrait, full head to toe, centered, full character outline naturally tapering; no foreground occlusion. Keep silhouette compact enough for a web hero illustration.
Style/medium: high quality 2D anime digital illustration with crisp fine linework and clean cel shading, matching the supplied original image.
Constraints: Background must be genuinely transparent; preserve transparency. NO rectangular image silhouette. NO straight cropped edges on the figure. NO cut-off hair tips, head, sleeves, fingers, skirt, knees, feet or shoes. No card, no gradient, no panel, no border, no opaque shadow, no sticker outline, no decorative geometry, no text, no logo, no watermark. Keep the outfit modest.
```

对全身版本进行以下针对性修正，最终采用此输出：

```text
Use case: background-extraction.
Asset type: transparent cutout illustration for a website.
Input image 1 is the edit target: the complete full-body cheerful 2D anime Hatsune Miku learning companion. Keep the SAME figure, face, full body pose, outfit, hair, blue notebook, peace sign, colors, crisp linework and cel shading.
CHANGE ONLY THESE TWO THINGS:
1. Remove EVERY trace of the cyan/gray glow, aura, haze and backdrop around the figure. There must be actual fully transparent alpha beyond the crisp character edges. The output is a plain cutout of the girl and her held notebook only. The spaces between hair strands, between limbs and outside all outlines must be clear transparent pixels. Do not include even faint smoke, gray shadows, cyan halo, color bleed, drop shadows, fuzzy vignette or any backdrop.
2. SHRINK the entire figure to fit safely inside the canvas and EXTEND the canvas with transparent empty space. Make a square canvas with at least 12% empty transparent margin on ALL FOUR SIDES. Head, ahoge, hair clips, ALL twin-tail hair tips and strands, fingers, elbows, skirt, both shoes must be fully inside the canvas. Preserve both shoes completely. All hair should end in natural curved/tapered tips inside the canvas. No part of the outline touches any canvas edge.
The empty background must be genuine transparency, no checkerboard printed into the image, no white/black rectangle. No text, no border, no panel, no logo. High quality polished 2D anime illustration.
```
