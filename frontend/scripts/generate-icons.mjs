// PWA 아이콘 생성기 (외부 의존성 없음: Node 내장 zlib만 사용).
// 디자인: 남색(indigo) 바탕 + 흰 책갈피 리본 + 리본 안의 작은 남색 점. 직접 만든 단순한 오리지널 도형이다.
//
//   node scripts/generate-icons.mjs     → public/ 에 PNG·SVG를 다시 만든다 (결과물은 커밋한다)
//
// 만드는 파일
//   pwa-192x192.png, pwa-512x512.png  : 일반 아이콘 (둥근 사각형, 모서리 투명)
//   maskable-icon-512x512.png         : 마스커블 (꽉 찬 바탕, 도형은 가운데 안전 영역 안)
//   apple-touch-icon-180x180.png      : iOS 홈 화면 (꽉 찬 바탕, iOS가 모서리를 둥글게 자른다)
//   favicon.svg                       : 브라우저 탭 아이콘

import { writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { deflateSync } from 'node:zlib'

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public')
const BG = [79, 70, 229] // #4f46e5
const FG = [255, 255, 255]

// ── 도형 (0~1 좌표) ─────────────────────────────
// 책갈피 리본: 위쪽 모서리가 둥근 직사각형 + 아래가 V자로 파인 모양
function ribbon(scale) {
  const w = 0.36 * scale
  const h = 0.5 * scale
  const x0 = 0.5 - w / 2
  const y0 = 0.5 - h / 2 - 0.01 * scale
  const notch = 0.15 * scale
  const r = 0.05 * scale
  return { x0, y0, x1: x0 + w, y1: y0 + h, notch, r, dotR: 0.055 * scale, dotY: y0 + 0.16 * scale }
}

function inRibbon(x, y, g) {
  if (x < g.x0 || x > g.x1 || y < g.y0 || y > g.y1) return false
  // 위쪽 둥근 모서리
  if (y < g.y0 + g.r) {
    const cx = x < g.x0 + g.r ? g.x0 + g.r : x > g.x1 - g.r ? g.x1 - g.r : x
    const cy = g.y0 + g.r
    if ((x - cx) ** 2 + (y - cy) ** 2 > g.r ** 2) return false
  }
  // 아래 V자 홈: 가운데(0.5)에서 y1 - notch까지 파인다
  const half = (g.x1 - g.x0) / 2
  const depth = g.notch * (1 - Math.abs(x - 0.5) / half)
  if (y > g.y1 - depth) return false
  return true
}

function inDot(x, y, g) {
  return (x - 0.5) ** 2 + (y - g.dotY) ** 2 <= g.dotR ** 2
}

function inRoundedSquare(x, y, radius) {
  const cx = Math.min(Math.max(x, radius), 1 - radius)
  const cy = Math.min(Math.max(y, radius), 1 - radius)
  return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2
}

// ── 래스터화 (4x4 슈퍼샘플링) ─────────────────────
function render(size, { rounded, scale }) {
  const g = ribbon(scale)
  const px = Buffer.alloc(size * size * 4)
  const S = 4
  for (let j = 0; j < size; j++) {
    for (let i = 0; i < size; i++) {
      let bg = 0
      let fg = 0
      for (let sj = 0; sj < S; sj++) {
        for (let si = 0; si < S; si++) {
          const x = (i + (si + 0.5) / S) / size
          const y = (j + (sj + 0.5) / S) / size
          const inBg = rounded ? inRoundedSquare(x, y, 0.22) : true
          if (!inBg) continue
          bg++
          if (inRibbon(x, y, g) && !inDot(x, y, g)) fg++
        }
      }
      const a = bg / (S * S)
      const t = bg ? fg / bg : 0
      const o = (j * size + i) * 4
      for (let c = 0; c < 3; c++) px[o + c] = Math.round(BG[c] * (1 - t) + FG[c] * t)
      px[o + 3] = Math.round(a * 255)
    }
  }
  return px
}

// ── PNG 인코딩 ───────────────────────────────────
const CRC_TABLE = new Uint32Array(256).map((_, n) => {
  let c = n
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
  return c >>> 0
})
function crc32(buf) {
  let c = 0xffffffff
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}
function chunk(type, data) {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length)
  const td = Buffer.concat([Buffer.from(type, 'ascii'), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(td))
  return Buffer.concat([len, td, crc])
}
function png(size, rgba) {
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8 // 비트 깊이
  ihdr[9] = 6 // RGBA
  const raw = Buffer.alloc(size * (size * 4 + 1))
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0
    rgba.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4)
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

function write(name, size, opts) {
  writeFileSync(join(OUT, name), png(size, render(size, opts)))
  console.log('wrote', name)
}

write('pwa-192x192.png', 192, { rounded: true, scale: 1 })
write('pwa-512x512.png', 512, { rounded: true, scale: 1 })
// 마스커블: 바깥 20%가 잘릴 수 있으므로 도형을 줄인다
write('maskable-icon-512x512.png', 512, { rounded: false, scale: 0.8 })
write('apple-touch-icon-180x180.png', 180, { rounded: false, scale: 0.9 })

// ── favicon.svg (같은 도형) ───────────────────────
{
  const g = ribbon(1)
  const f = (n) => +(n * 100).toFixed(2)
  const path = [
    `M${f(g.x0)} ${f(g.y0 + g.r)}`,
    `A${f(g.r)} ${f(g.r)} 0 0 1 ${f(g.x0 + g.r)} ${f(g.y0)}`,
    `H${f(g.x1 - g.r)}`,
    `A${f(g.r)} ${f(g.r)} 0 0 1 ${f(g.x1)} ${f(g.y0 + g.r)}`,
    `V${f(g.y1)}`,
    `L50 ${f(g.y1 - g.notch)}`,
    `L${f(g.x0)} ${f(g.y1)}Z`,
  ].join(' ')
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="22" fill="#4f46e5"/><path d="${path}" fill="#fff"/><circle cx="50" cy="${f(g.dotY)}" r="${f(g.dotR)}" fill="#4f46e5"/></svg>\n`
  writeFileSync(join(OUT, 'favicon.svg'), svg)
  console.log('wrote favicon.svg')
}
