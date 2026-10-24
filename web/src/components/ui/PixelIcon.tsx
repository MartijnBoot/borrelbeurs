/**
 * BorrelBeurs's own pixel icons (B-02 SD1, SD2, SD5; PD2): a grid from
 * `pixelIcons.json` drawn as one inline SVG path, one `h`-run per row's run of
 * `#`. One colour -- `currentColor`, so the icon is the surrounding text's colour
 * under every theme --, 1em tall and crisp at any size. Decorative
 * (`aria-hidden`) unless it is given a `label` (SD11). The favicon's grid is not
 * drawn here; `scripts/pixel_icons.py` makes the PNG from it.
 */
import styles from './PixelIcon.module.css'
import grids from './pixelIcons.json'

export type PixelIconName = Exclude<keyof typeof grids, 'favicon'>

function path(grid: readonly string[]): string {
  return grid
    .flatMap((row, y) =>
      [...row.matchAll(/#+/g)].map(
        ({ 0: run, index: x }) => `M${x} ${y}h${run.length}v1h-${run.length}z`,
      ),
    )
    .join('')
}

export function PixelIcon({
  name,
  label,
  className,
}: {
  name: PixelIconName
  label?: string
  className?: string
}) {
  const grid = grids[name]
  const a11y = label === undefined ? { 'aria-hidden': true } : { role: 'img', 'aria-label': label }
  return (
    <svg
      viewBox={`0 0 ${grid.length} ${grid.length}`}
      width="1em"
      height="1em"
      fill="currentColor"
      shapeRendering="crispEdges"
      focusable="false"
      className={className === undefined ? styles.icon : `${styles.icon} ${className}`}
      {...a11y}
    >
      <path d={path(grid)} />
    </svg>
  )
}
