/**
 * EmberParticles — Phase 7 D&D aesthetic.
 *
 * Renders a small number of floating amber ember particles in the
 * lower portion of the viewport. Very low cost: 4–6 divs with CSS animations.
 * Only visible on the Table page (passed as a prop or imported there directly).
 */

import { useMemo } from 'react'

const EMBER_COUNT = 5

export default function EmberParticles() {
  const embers = useMemo(() => {
    return Array.from({ length: EMBER_COUNT }, (_, i) => ({
      id: i,
      left: `${10 + i * 18 + Math.sin(i * 1.7) * 8}%`,
      delay: `${i * 1.3 + Math.cos(i) * 0.5}s`,
      duration: `${4.5 + i * 0.7}s`,
      size: `${2 + (i % 2)}px`,
    }))
  }, [])

  return (
    <>
      {embers.map((e) => (
        <div
          key={e.id}
          className="ember"
          style={{
            left: e.left,
            width: e.size,
            height: e.size,
            animationDelay: e.delay,
            animationDuration: e.duration,
          }}
        />
      ))}
    </>
  )
}
