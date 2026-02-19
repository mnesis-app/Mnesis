#!/usr/bin/env node
/**
 * Generates the Mnesis palimpseste dock icon following Apple HIG:
 * - Full edge-to-edge OPAQUE background (macOS applies squircle mask itself)
 * - 1024×1024 PNG output for app.dock.setIcon()
 * - Uses rsvg-convert (brew install librsvg) for accurate SVG→PNG
 */

const fs = require('fs')
const path = require('path')
const { execSync } = require('child_process')

// ── Layout constants ─────────────────────────────────────────────────────────
const SIZE = 1024    // canvas size
const BG = '#0D0D0D'  // near-black, matches app background
const FG = '#F5F3EE'  // warm white, matches app text/icon colour

// The palimpseste mark in a 0-100 unit coordinate system.
// We map it to ~56% of the canvas, vertically centred with slight upward bias.
// Mark spans x: 10-90 = 80 units wide,  y: 16-93 = 77 units tall

const MARK_RATIO = 0.56      // mark width as fraction of canvas
const MARK_PX = SIZE * MARK_RATIO  // = 573.44 px
const SCALE = MARK_PX / 80      // px per unit  (80 = x span 10→90)
const OX = (SIZE - MARK_PX) / 2 - 10 * SCALE  // left origin so x=10 starts at padding
const MARK_H = 77 * SCALE        // total height in px (y: 16→93)
const OY = (SIZE - MARK_H) / 2 - 16 * SCALE - SIZE * 0.02 // centre vertically, slight up

function px(u) { return (OX + u * SCALE).toFixed(2) }
function py(u) { return (OY + u * SCALE).toFixed(2) }

// Stroke widths taper row-by-row (wider at top = denser text, thinner below = fading)
const sw = [14, 14, 12.5, 11, 9.8, 8.3, 7.4, 7.4]

// ── SVG source ───────────────────────────────────────────────────────────────
// Full opaque background — Apple HIG: "icons should have full edge-to-edge opacity"
// macOS applies the squircle mask automatically in the dock.
const svg = `<svg width="${SIZE}" height="${SIZE}" viewBox="0 0 ${SIZE} ${SIZE}" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Full opaque background — macOS applies squircle mask itself -->
  <rect width="${SIZE}" height="${SIZE}" fill="${BG}"/>

  <!-- Palimpseste mark: fragmenting lines, top → bottom, denser → sparser -->
  <!-- Row 1: intact -->
  <line x1="${px(10)}" y1="${py(16)}" x2="${px(90)}" y2="${py(16)}" stroke="${FG}" stroke-width="${sw[0]}" stroke-linecap="round"/>
  <!-- Row 2: one gap -->
  <line x1="${px(10)}" y1="${py(27)}" x2="${px(54)}" y2="${py(27)}" stroke="${FG}" stroke-width="${sw[1]}" stroke-linecap="round"/>
  <line x1="${px(60)}" y1="${py(27)}" x2="${px(90)}" y2="${py(27)}" stroke="${FG}" stroke-width="${sw[1]}" stroke-linecap="round"/>
  <!-- Row 3: two gaps -->
  <line x1="${px(10)}" y1="${py(38)}" x2="${px(38)}" y2="${py(38)}" stroke="${FG}" stroke-width="${sw[2]}" stroke-linecap="round"/>
  <line x1="${px(44)}" y1="${py(38)}" x2="${px(68)}" y2="${py(38)}" stroke="${FG}" stroke-width="${sw[2]}" stroke-linecap="round"/>
  <line x1="${px(74)}" y1="${py(38)}" x2="${px(90)}" y2="${py(38)}" stroke="${FG}" stroke-width="${sw[2]}" stroke-linecap="round"/>
  <!-- Row 4: three gaps -->
  <line x1="${px(10)}" y1="${py(49)}" x2="${px(28)}" y2="${py(49)}" stroke="${FG}" stroke-width="${sw[3]}" stroke-linecap="round"/>
  <line x1="${px(35)}" y1="${py(49)}" x2="${px(52)}" y2="${py(49)}" stroke="${FG}" stroke-width="${sw[3]}" stroke-linecap="round"/>
  <line x1="${px(59)}" y1="${py(49)}" x2="${px(73)}" y2="${py(49)}" stroke="${FG}" stroke-width="${sw[3]}" stroke-linecap="round"/>
  <line x1="${px(79)}" y1="${py(49)}" x2="${px(90)}" y2="${py(49)}" stroke="${FG}" stroke-width="${sw[3]}" stroke-linecap="round"/>
  <!-- Row 5: four gaps -->
  <line x1="${px(10)}" y1="${py(60)}" x2="${px(22)}" y2="${py(60)}" stroke="${FG}" stroke-width="${sw[4]}" stroke-linecap="round"/>
  <line x1="${px(29)}" y1="${py(60)}" x2="${px(40)}" y2="${py(60)}" stroke="${FG}" stroke-width="${sw[4]}" stroke-linecap="round"/>
  <line x1="${px(47)}" y1="${py(60)}" x2="${px(57)}" y2="${py(60)}" stroke="${FG}" stroke-width="${sw[4]}" stroke-linecap="round"/>
  <line x1="${px(63)}" y1="${py(60)}" x2="${px(72)}" y2="${py(60)}" stroke="${FG}" stroke-width="${sw[4]}" stroke-linecap="round"/>
  <line x1="${px(78)}" y1="${py(60)}" x2="${px(87)}" y2="${py(60)}" stroke="${FG}" stroke-width="${sw[4]}" stroke-linecap="round"/>
  <!-- Row 6: five gaps -->
  <line x1="${px(10)}" y1="${py(71)}" x2="${px(18)}" y2="${py(71)}" stroke="${FG}" stroke-width="${sw[5]}" stroke-linecap="round"/>
  <line x1="${px(25)}" y1="${py(71)}" x2="${px(32)}" y2="${py(71)}" stroke="${FG}" stroke-width="${sw[5]}" stroke-linecap="round"/>
  <line x1="${px(40)}" y1="${py(71)}" x2="${px(46)}" y2="${py(71)}" stroke="${FG}" stroke-width="${sw[5]}" stroke-linecap="round"/>
  <line x1="${px(53)}" y1="${py(71)}" x2="${px(59)}" y2="${py(71)}" stroke="${FG}" stroke-width="${sw[5]}" stroke-linecap="round"/>
  <line x1="${px(66)}" y1="${py(71)}" x2="${px(72)}" y2="${py(71)}" stroke="${FG}" stroke-width="${sw[5]}" stroke-linecap="round"/>
  <line x1="${px(78)}" y1="${py(71)}" x2="${px(84)}" y2="${py(71)}" stroke="${FG}" stroke-width="${sw[5]}" stroke-linecap="round"/>
  <!-- Row 7: just dots -->
  <line x1="${px(13)}" y1="${py(82)}" x2="${px(17)}" y2="${py(82)}" stroke="${FG}" stroke-width="${sw[6]}" stroke-linecap="round"/>
  <line x1="${px(26)}" y1="${py(82)}" x2="${px(30)}" y2="${py(82)}" stroke="${FG}" stroke-width="${sw[6]}" stroke-linecap="round"/>
  <line x1="${px(40)}" y1="${py(82)}" x2="${px(44)}" y2="${py(82)}" stroke="${FG}" stroke-width="${sw[6]}" stroke-linecap="round"/>
  <line x1="${px(53)}" y1="${py(82)}" x2="${px(57)}" y2="${py(82)}" stroke="${FG}" stroke-width="${sw[6]}" stroke-linecap="round"/>
  <line x1="${px(66)}" y1="${py(82)}" x2="${px(70)}" y2="${py(82)}" stroke="${FG}" stroke-width="${sw[6]}" stroke-linecap="round"/>
  <line x1="${px(79)}" y1="${py(82)}" x2="${px(83)}" y2="${py(82)}" stroke="${FG}" stroke-width="${sw[6]}" stroke-linecap="round"/>
  <!-- Row 8: barely there -->
  <line x1="${px(15)}" y1="${py(93)}" x2="${px(18)}" y2="${py(93)}" stroke="${FG}" stroke-width="${sw[7]}" stroke-linecap="round"/>
  <line x1="${px(32)}" y1="${py(93)}" x2="${px(35)}" y2="${py(93)}" stroke="${FG}" stroke-width="${sw[7]}" stroke-linecap="round"/>
  <line x1="${px(52)}" y1="${py(93)}" x2="${px(55)}" y2="${py(93)}" stroke="${FG}" stroke-width="${sw[7]}" stroke-linecap="round"/>
  <line x1="${px(72)}" y1="${py(93)}" x2="${px(75)}" y2="${py(93)}" stroke="${FG}" stroke-width="${sw[7]}" stroke-linecap="round"/>
</svg>`

// ── Write SVG ─────────────────────────────────────────────────────────────────
const iconsDir = path.join(__dirname, '../assets/icons/mnesis.iconset')
fs.mkdirSync(iconsDir, { recursive: true })
const svgPath = path.join(__dirname, '../assets/icons/mnesis_source.svg')
fs.writeFileSync(svgPath, svg)
console.log('✅ SVG written:', svgPath)

// ── Convert SVG → PNG using rsvg-convert (accurate, supports full colour) ────
const sizes = [16, 32, 64, 128, 256, 512, 1024]
try {
    for (const s of sizes) {
        const out = path.join(iconsDir, `icon_${s}x${s}.png`)
        execSync(`rsvg-convert -w ${s} -h ${s} -o "${out}" "${svgPath}"`)
        // @2x copies for iconutil
        const half = s / 2
        if (half >= 16) {
            const out2x = path.join(iconsDir, `icon_${half}x${half}@2x.png`)
            fs.copyFileSync(out, out2x)
        }
    }
    console.log('✅ PNG sizes generated via rsvg-convert')

    // ── Build .icns ───────────────────────────────────────────────────────────
    const icnsPath = path.join(__dirname, '../assets/icons/mnesis.icns')
    execSync(`iconutil -c icns "${iconsDir}" -o "${icnsPath}"`)
    console.log('✅ ICNS written:', icnsPath)

} catch (e) {
    console.error('❌ Error generating icon:', e.message)
    process.exit(1)
}
