import { useEffect, useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import SplitType from "split-type";
import NeonIcon from "@/components/icons/NeonIcon";

gsap.registerPlugin(ScrollTrigger);

class TextSplitter {
  textElement: HTMLElement;
  onResize?: () => void;
  splitText: SplitType;
  private observer: ResizeObserver = new ResizeObserver(() => {});

  constructor(textElement: HTMLElement, options: { resizeCallback?: () => void } = {}) {
    this.textElement = textElement;
    this.onResize = options.resizeCallback;
    this.splitText = new SplitType(this.textElement, { types: "words,chars" });
    this.setupResizeObserver();
  }

  getChars() {
    return this.splitText.chars || [];
  }

  getWords() {
    return this.splitText.words || [];
  }

  setupResizeObserver() {
    this.observer = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        this.splitText.split({});
        if (this.onResize) {
          this.onResize();
        }
      });
    });
    this.observer.observe(this.textElement);
  }

  destroy() {
    this.observer.disconnect();
    this.splitText.revert();
  }
}

export default function HeroSection() {
  const containerRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const subtitleRef = useRef<HTMLParagraphElement>(null);
  const splitterRef = useRef<TextSplitter | null>(null);

  useEffect(() => {
    if (!titleRef.current || !subtitleRef.current || !containerRef.current) return;

    const ctx = gsap.context(() => {
      // Text reveal animation for subtitle
      const subSplitter = new TextSplitter(subtitleRef.current!, {
        resizeCallback: () => {
          ScrollTrigger.refresh();
        },
      });

      const subChars = subSplitter.getChars();
      if (subChars.length > 0) {
        gsap.timeline({
          scrollTrigger: {
            trigger: subtitleRef.current,
            start: "top bottom-=10%",
            end: "bottom center+=10%",
            scrub: true,
          },
        })
          .from(subChars, { scaleY: 0, transformOrigin: "50% 0%", stagger: 0.04 }, 0)
          .from(subChars, { scaleX: 0, ease: "expo.out", transformOrigin: "50% 50%", stagger: 0.04 }, 0)
          .from(subChars, { opacity: 0, ease: "back.in", duration: 0.8, stagger: 0.04 }, 0)
          .fromTo(subChars, { xPercent: 300 }, { xPercent: -200, stagger: 0.05 }, 0);
      }

      // Main title spread animation
      splitterRef.current = new TextSplitter(titleRef.current!, {
        resizeCallback: () => {
          ScrollTrigger.refresh();
        },
      });

      const words = splitterRef.current.getWords();
      if (words.length > 0) {
        gsap.timeline({
          scrollTrigger: {
            trigger: titleRef.current,
            start: "top bottom",
            end: "+200vh",
            scrub: true,
            pin: true,
          },
        })
          .from(words, { rotateX: -90, rotateY: -25, transformOrigin: "50% 50%, -200px", stagger: 0.05 })
          .to(words, { z: 400, xPercent: -100, yPercent: -150, opacity: 0.2, stagger: 0.08 }, 0.2);
      }
    }, containerRef);

    return () => {
      ctx.revert();
      if (splitterRef.current) {
        splitterRef.current.destroy();
      }
    };
  }, []);

  return (
    <section ref={containerRef} className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden">
      {/* Background grid glow */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-[#00E5FF]/5 rounded-full blur-[120px]" />
        <div className="absolute bottom-1/4 right-1/4 w-[400px] h-[400px] bg-[#7B2D8E]/8 rounded-full blur-[100px]" />
      </div>

      {/* Hero Title */}
      <div className="relative z-10 text-center perspective-[1000px]">
        <h1
          ref={titleRef}
          id="hero-title"
          className="font-display text-[12vw] sm:text-[15vw] leading-none tracking-tight text-white whitespace-nowrap"
          style={{ transformStyle: "preserve-3d" }}
        >
          THE ORION PROTOCOL
        </h1>

        <p
          ref={subtitleRef}
          className="mt-8 text-sm sm:text-base md:text-lg text-white/60 max-w-xl mx-auto leading-relaxed px-4"
        >
          Autonomous acquisition infrastructure for the machine-to-machine economy.
        </p>

        {/* Status indicators */}
        <div className="mt-12 flex items-center justify-center gap-6">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#39FF14] animate-pulse" />
            <span className="text-[10px] uppercase tracking-[0.2em] text-white/40">All Systems Active</span>
          </div>
          <div className="w-px h-4 bg-white/10" />
          <div className="flex items-center gap-2">
            <NeonIcon type="broadcast" size={12} color="#39FF14" active />
            <span className="text-[10px] uppercase tracking-[0.2em] text-white/40">3 Modules Online</span>
          </div>
        </div>
      </div>
    </section>
  );
}
