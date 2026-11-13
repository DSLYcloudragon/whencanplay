# 图片资源放这里

## 目录约定

```
core/static/core/custom.css      ← 你改的样式
core/static/core/assets/         ← 图片放这里
```

在 `custom.css` 里用**相对路径**引用，不要写 `/static/...`：

```css
/* 正确 */
body.page-index { background-image: url("assets/bg-hero.webp"); }

/* 错误（换环境会失效） */
body { background-image: url("/static/core/assets/bg-hero.webp"); }
```

---

## 带宽预算（重要）

服务器出口带宽 **2 Mbps ≈ 250 KB/秒**。这不是不能用图，而是要有节制。

| 项目 | 上限 |
|---|---|
| **单张图片** | ≤ 150 KB |
| **全站图片总量** | ≤ 400 KB |
| 推荐格式 | **WebP**（同等画质比 JPG 小 30~50%） |
| 不推荐 | PNG（照片类会大到 1 MB 以上） |
| 禁止 | 未压缩的导出图、4K 原图 |

### 换算一下

```
一张 150 KB 的图 → 首次访问多等 0.6 秒
缓存之后          → 0 秒（服务器设了 30 天缓存）
```

**但如果每个页面都放一张大图**，首次访问累计要 3 秒以上，用户就跑了。

---

## 实际建议

**只在一两个地方用大图**：

| 页面 | 建议 |
|---|---|
| 落地页 `/` | ✅ 一张主视觉背景，值得 |
| 登录 / 注册 | ✅ 可以复用落地页那张 |
| 群热力图 | ⚠️ 可以，但要淡（热力图本身是信息密集区，背景不能抢） |
| 其它页面 | ❌ 用纯色 / 渐变就行 |

---

## 怎么压缩

### 在线

- <https://squoosh.app/> —— 拖进去，选 WebP，质量 75~85

### 命令行

```bash
# 需要先装 cwebp
cwebp -q 80 input.png -o output.webp
```

### 检查大小

Windows 上右键图片 → 属性，看「大小」。
**超过 150 KB 就回去重新压。**

---

## 更省带宽的替代方案

有时候**不加图反而更好看**：

| 手法 | 效果 |
|---|---|
| CSS 渐变 | `linear-gradient` / `radial-gradient`，零流量 |
| 噪点纹理 | 用 SVG `feTurbulence` 生成，几 KB |
| 网格 / 点阵背景 | 用 `repeating-linear-gradient`，零流量 |
| 模糊光斑 | `radial-gradient` 多层叠加 |
| 内联 SVG 图标 | 直接写进 CSS 的 `background-image: url("data:image/svg+xml,...")` |

这些在深色界面上效果很好，而且**完全不增加加载时间**。优先考虑。

---

## 命名

```
assets/bg-hero.webp       落地页主视觉
assets/bg-auth.webp       登录页背景
assets/noise.svg          噪点纹理
assets/logo.svg           Logo
```

名字见名知意，别用 `1.png`、`图片.png`、`新图片(2).png`。
