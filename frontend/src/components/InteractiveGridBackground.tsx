import { useEffect, useRef } from 'react'

interface Props {
  darkMode: boolean
}

export default function InteractiveGridBackground({ darkMode }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let width = 0
    let height = 0
    let animationFrameId: number

    // Grid configuration
    const dotSpacing = 10
    const baseDotRadius = 0.5
    const highlightRadius = 200

    // Mouse state
    const mouse = { x: 0, y: 0, active: false }
    const box = { x: 0, y: 0 }
    const ghost = { x: 0, y: 0, vx: 1.8, vy: 1.2 }

    function resize() {
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      width = rect.width
      height = rect.height
      canvas.width = width
      canvas.height = height

      if (box.x === 0 && box.y === 0) {
        box.x = width / 2
        box.y = height / 2
        ghost.x = width / 2
        ghost.y = height / 2
      }
    }

    window.addEventListener('resize', resize)
    resize()

    // Track mouse moves relative to canvas to support sidebar offset offsets
    const handleMouseMove = (e: MouseEvent) => {
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      mouse.x = e.clientX - rect.left
      mouse.y = e.clientY - rect.top
      mouse.active = true
    }

    const handleMouseLeave = () => {
      mouse.active = false
      ghost.x = box.x
      ghost.y = box.y
    }

    const handleMouseEnter = () => {
      mouse.active = true
    }

    window.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseleave', handleMouseLeave)
    document.addEventListener('mouseenter', handleMouseEnter)

    function animate() {
      if (!canvas || !ctx) return
      ctx.clearRect(0, 0, width, height)

      const time = Date.now() * 0.003

      // Update Ghost position (bouncing around the screen)
      if (!mouse.active) {
        ghost.x += ghost.vx
        ghost.y += ghost.vy

        // Bounce off edges
        if (ghost.x < 0 || ghost.x > width) ghost.vx *= -1
        if (ghost.y < 0 || ghost.y > height) ghost.vy *= -1
      }

      // Determine target (Mouse or Ghost)
      const target = mouse.active ? mouse : ghost

      let targetX = target.x
      let targetY = target.y

      if (mouse.active) {
        // Gentle floating orbit around the mouse pointer so it never stands completely still
        targetX += Math.sin(time * 1.5) * 12
        targetY += Math.cos(time * 1.1) * 12
      }

      // Constant speed steering (so it never rushes, speed is constant always)
      const dx = targetX - box.x
      const dy = targetY - box.y
      const distance = Math.sqrt(dx * dx + dy * dy)
      
      const speedLimit = mouse.active ? 3.5 : 1.5

      if (distance > speedLimit) {
        box.x += (dx / distance) * speedLimit
        box.y += (dy / distance) * speedLimit
      } else {
        box.x = targetX
        box.y = targetY
      }

      // Base grid dot color
      const dotColorBase = darkMode ? '#27272a' : '#e4e4e7'
      const maxDistLimit = highlightRadius + 38
      const maxDistLimitSq = maxDistLimit * maxDistLimit

      // Draw the grid
      for (let x = 0; x < width; x += dotSpacing) {
        for (let y = 0; y < height; y += dotSpacing) {
          const dx = x - box.x
          const dy = y - box.y
          const distSq = dx * dx + dy * dy

          let dotRadius = baseDotRadius
          let dotColor = dotColorBase

          // Optimize: Only run square root & complex trig math if near highlight zone
          if (distSq < maxDistLimitSq) {
            const dist = Math.sqrt(distSq)
            const angle = Math.atan2(dy, dx)

            // Compose 3 sine/cosine waves for fluid jelly-blob deformation
            const wave = Math.sin(angle * 3 + time) * 20 +
              Math.cos(angle * 5 - time * 1.2) * 12 +
              Math.sin(angle * 7 + time * 0.8) * 6
            const dynamicHighlightRadius = highlightRadius + wave

            if (dist < dynamicHighlightRadius) {
              const intensity = 1 - (dist / dynamicHighlightRadius)

              // Outward radiating HSL color spectrum with slow, fine shifts
              const hue = Math.floor((220 + time * 6 - dist * 0.08 + 360) % 360)
              const saturation = darkMode ? 100 : 90
              const lightness = darkMode
                ? Math.floor(50 + intensity * 15)
                : Math.floor(40 + intensity * 10)
              const alpha = 0.15 + intensity * 0.85

              dotColor = `hsla(${hue}, ${saturation}%, ${lightness}%, ${alpha})`
              dotRadius = baseDotRadius + intensity * 1.0
            }
          }

          ctx.beginPath()
          ctx.arc(x, y, dotRadius, 0, Math.PI * 2)
          ctx.fillStyle = dotColor
          ctx.fill()
        }
      }

      animationFrameId = requestAnimationFrame(animate)
    }

    animate()

    return () => {
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseleave', handleMouseLeave)
      document.removeEventListener('mouseenter', handleMouseEnter)
      cancelAnimationFrame(animationFrameId)
    }
  }, [darkMode])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full pointer-events-none z-0"
    />
  )
}
