# 半身学习伙伴 v3

使用内置 imagegen 编辑旧的透明 Miku 素材，保存为 `<project-root>/frontend/public/images/miku-bust-v3.png`。原素材保留。

首页与学习助手采用半身图，助手显示从 165px 提高到 270px，宽度最多 245px，保持透明背景与 contain。已用实际浏览器检查桌面深色、手机布局及 JavaScript 错误；截图为 `docs/screenshots/miku-bust-sidebar.png` 和 `miku-bust-mobile.png`。此次为插画与样式调整，没有运行模型或修改转录内容。

最终提示词：

```text
Edit target: the provided Hatsune Miku learning companion. Create a polished 2D anime UPPER BODY / WAIST-UP portrait for a small web sidebar. Preserve her identity, turquoise twin tails, cheerful large clear smiling face with one eye wink, gray collared sleeveless top and turquoise tie, black detached sleeves, a blue notebook hugged to her chest, and one friendly peace-sign hand. Composition: face much larger and clearly legible, head and shoulders dominate upper half, waist-up only, NO legs or feet. Both hands and notebook visible. Genuine transparent alpha background, absolutely no backdrop, panel, rectangle, glow, aura, shadow or text. The complete waist-up illustration has a natural irregular silhouette: twin tails curve around the shoulders and taper to natural tips, clothes have a curved slightly pointed hem ending near the waist, notebook and sleeves fully inside the canvas. Do not truncate arms, fingertips, top of head or hair at canvas edges. Leave a modest 5 percent transparent safety margin around the entire silhouette; fill most of the image with the character, avoid excessive blank space. Keep crisp detailed cheerful face, modest outfit, clean anime cel shading. No flat horizontal crop across the body or hair; let the small portrait end naturally with the clothing hem and curved hair tips, like a beautifully finished bust sticker WITHOUT sticker border. Output portrait aspect ratio if possible. Asset intended to display at about 260px tall and 250px wide. Keep no opaque background or checkerboard.
```
