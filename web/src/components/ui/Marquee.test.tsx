// @vitest-environment jsdom
// The marquee's animation against a stubbed Web Animations API (AC33): jsdom
// has none, so `Element.prototype.animate` records what the component asks.
import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Marquee, type MarqueeItem } from './Marquee'

interface FakeAnimation {
  keyframes: Keyframe[]
  currentTime: number | null
  playbackRate: number
  updatePlaybackRate: ReturnType<typeof vi.fn>
  cancel: ReturnType<typeof vi.fn>
  pause: ReturnType<typeof vi.fn>
  play: ReturnType<typeof vi.fn>
}

const animations: FakeAnimation[] = []

beforeEach(() => {
  animations.length = 0
  Element.prototype.animate = vi.fn((keyframes: Keyframe[]) => {
    const animation: FakeAnimation = {
      keyframes,
      currentTime: 0,
      playbackRate: 1,
      updatePlaybackRate: vi.fn((rate: number) => {
        animation.playbackRate = rate
      }),
      cancel: vi.fn(),
      pause: vi.fn(),
      play: vi.fn(),
    }
    animations.push(animation)
    return animation as unknown as Animation
  }) as unknown as Element['animate']
})

afterEach(() => {
  cleanup()
  delete (Element.prototype as Partial<Element>).animate
})

const item = (key: string, text: string): MarqueeItem => ({ key, parts: [{ text }] })

describe('Marquee', () => {
  it('renders every part as text, never as HTML (AC32)', () => {
    const xss = '<img src=x onerror=alert(1)>'
    const { container } = render(<Marquee variant="loop" items={[item('a', xss)]} />)
    expect(container.textContent).toBe(xss)
    expect(container.querySelector('img')).toBeNull()
  })

  it('keeps the animation when content changes but the count does not (AC33)', () => {
    const { rerender } = render(<Marquee variant="loop" items={[item('a', '1'), item('b', '2')]} />)
    expect(animations).toHaveLength(1)
    animations[0].currentTime = 12_345

    rerender(<Marquee variant="loop" items={[item('a', '3'), item('b', '4')]} />)

    expect(animations).toHaveLength(1)
    expect(animations[0].cancel).not.toHaveBeenCalled()
    expect(animations[0].currentTime).toBe(12_345)
  })

  it('carries currentTime into the new animation when the count changes (AC33)', () => {
    const { rerender } = render(<Marquee variant="news" items={[item('a', '1')]} />)
    animations[0].currentTime = 12_345

    rerender(<Marquee variant="news" items={[item('a', '1'), item('b', '2')]} />)

    expect(animations).toHaveLength(2)
    expect(animations[0].cancel).toHaveBeenCalledOnce()
    expect(animations[1].currentTime).toBe(12_345)
  })

  it('changes speed with updatePlaybackRate, and a recreated animation keeps the rate', () => {
    const items = [item('a', '1')]
    const { rerender } = render(<Marquee variant="news" items={items} />)

    rerender(<Marquee variant="news" items={items} playbackRate={2.5} />)
    expect(animations).toHaveLength(1)
    expect(animations[0].updatePlaybackRate).toHaveBeenCalledWith(2.5)

    rerender(<Marquee variant="news" items={[...items, item('b', '2')]} playbackRate={2.5} />)
    expect(animations[1].playbackRate).toBe(2.5)
  })

  it('pauses on hover and resumes after (SD24)', () => {
    const { container } = render(<Marquee variant="loop" items={[item('a', '1')]} />)
    fireEvent.mouseEnter(container.firstElementChild!)
    expect(animations[0].pause).toHaveBeenCalledOnce()
    fireEvent.mouseLeave(container.firstElementChild!)
    expect(animations[0].play).toHaveBeenCalledOnce()
  })

  it('scrolls the loop by half its width and the news across the screen (koers.html:49-50)', () => {
    render(<Marquee variant="loop" items={[item('a', '1')]} />)
    render(<Marquee variant="news" items={[item('a', '1')]} />)
    expect(animations.map((a) => a.keyframes)).toEqual([
      [{ transform: 'translateX(0)' }, { transform: 'translateX(-50%)' }],
      [{ transform: 'translateX(100vw)' }, { transform: 'translateX(-100%)' }],
    ])
  })
})
