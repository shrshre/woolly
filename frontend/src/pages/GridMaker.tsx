// Colorwork pixel grid maker: canvas-based painting + image-to-grid conversion.

import { useEffect, useRef, useState, type ChangeEvent, type PointerEvent } from "react";
import { imageToGrid } from "../utils/quantize";

const MAX_DIM = 50;
const MAX_COLORS = 8;
const CANVAS_MAX_PX = 600;
const EXPORT_CELL_PX = 24;

const DEFAULT_PALETTE = ["#800020", "#c9a800", "#2c1810", "#e8e0d5"];

type Cells = (string | null)[];

function resizeCells(cells: Cells, oldW: number, oldH: number, newW: number, newH: number): Cells {
  const next: Cells = new Array(newW * newH).fill(null);
  for (let y = 0; y < Math.min(oldH, newH); y++) {
    for (let x = 0; x < Math.min(oldW, newW); x++) {
      next[y * newW + x] = cells[y * oldW + x];
    }
  }
  return next;
}

export function GridMaker() {
  const [width, setWidth] = useState(24);
  const [height, setHeight] = useState(24);
  const [cells, setCells] = useState<Cells>(() => new Array(24 * 24).fill(null));
  const [palette, setPalette] = useState<string[]>(DEFAULT_PALETTE);
  const [activeColor, setActiveColor] = useState(0);
  const [erasing, setErasing] = useState(false);
  const [detail, setDetail] = useState(32);
  const [colorCount, setColorCount] = useState(6);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const paintingRef = useRef(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const cellPx = Math.max(6, Math.floor(CANVAS_MAX_PX / Math.max(width, height)));

  // Redraw the canvas whenever the grid changes
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d")!;

    canvas.width = width * cellPx;
    canvas.height = height * cellPx;

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const color = cells[y * width + x];
        if (color) {
          ctx.fillStyle = color;
          ctx.fillRect(x * cellPx, y * cellPx, cellPx, cellPx);
        }
      }
    }

    // Gridlines
    ctx.strokeStyle = "#e8e0d5";
    ctx.lineWidth = 1;
    for (let x = 0; x <= width; x++) {
      ctx.beginPath();
      ctx.moveTo(x * cellPx + 0.5, 0);
      ctx.lineTo(x * cellPx + 0.5, height * cellPx);
      ctx.stroke();
    }
    for (let y = 0; y <= height; y++) {
      ctx.beginPath();
      ctx.moveTo(0, y * cellPx + 0.5);
      ctx.lineTo(width * cellPx, y * cellPx + 0.5);
      ctx.stroke();
    }
  }, [cells, width, height, cellPx]);

  function paintAt(event: PointerEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.floor(((event.clientX - rect.left) / rect.width) * width);
    const y = Math.floor(((event.clientY - rect.top) / rect.height) * height);
    if (x < 0 || x >= width || y < 0 || y >= height) return;

    const value = erasing ? null : palette[activeColor];
    setCells((prev) => {
      const idx = y * width + x;
      if (prev[idx] === value) return prev;
      const next = [...prev];
      next[idx] = value;
      return next;
    });
  }

  function handlePointerDown(event: PointerEvent<HTMLCanvasElement>) {
    paintingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    paintAt(event);
  }

  function handlePointerMove(event: PointerEvent<HTMLCanvasElement>) {
    if (paintingRef.current) paintAt(event);
  }

  function handlePointerUp() {
    paintingRef.current = false;
  }

  function applyDimension(dim: "w" | "h", raw: string) {
    const value = Math.max(1, Math.min(MAX_DIM, Number(raw) || 1));
    if (dim === "w") {
      setCells((prev) => resizeCells(prev, width, height, value, height));
      setWidth(value);
    } else {
      setCells((prev) => resizeCells(prev, width, height, width, value));
      setHeight(value);
    }
  }

  function updatePaletteColor(index: number, hex: string) {
    setPalette((prev) => prev.map((c, i) => (i === index ? hex : c)));
  }

  function addColor() {
    if (palette.length >= MAX_COLORS) return;
    setPalette((prev) => [...prev, "#6b4c3b"]);
    setActiveColor(palette.length);
    setErasing(false);
  }

  function removeColor(index: number) {
    if (palette.length <= 1) return;
    const removed = palette[index];
    setPalette((prev) => prev.filter((_, i) => i !== index));
    setActiveColor((prev) => Math.min(prev > index ? prev - 1 : prev, palette.length - 2));
    // Clear painted cells of the removed color
    setCells((prev) => prev.map((c) => (c === removed ? null : c)));
  }

  function clearGrid() {
    setCells(new Array(width * height).fill(null));
  }

  function exportPng() {
    const canvas = document.createElement("canvas");
    canvas.width = width * EXPORT_CELL_PX;
    canvas.height = height * EXPORT_CELL_PX;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const color = cells[y * width + x];
        if (color) {
          ctx.fillStyle = color;
          ctx.fillRect(x * EXPORT_CELL_PX, y * EXPORT_CELL_PX, EXPORT_CELL_PX, EXPORT_CELL_PX);
        }
      }
    }

    const link = document.createElement("a");
    link.download = `woolly-grid-${width}x${height}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
  }

  function handleImageUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const grid = imageToGrid(img, detail, colorCount);
      setWidth(grid.width);
      setHeight(grid.height);
      setCells(grid.cells);
      setPalette(grid.palette.slice(0, MAX_COLORS));
      setActiveColor(0);
      setErasing(false);
      URL.revokeObjectURL(url);
    };
    img.src = url;
    event.target.value = ""; // allow re-uploading the same file
  }

  return (
    <section className="grid-page">
      <div className="projects-header">
        <h1 className="library-title">Grid maker</h1>
        <div className="grid-header-actions">
          <button type="button" className="btn-ghost" onClick={clearGrid}>
            Clear
          </button>
          <button type="button" className="btn-primary" onClick={exportPng}>
            Export PNG
          </button>
        </div>
      </div>

      <div className="grid-layout">
        <div className="grid-canvas-wrap">
          <canvas
            ref={canvasRef}
            className={erasing ? "grid-canvas erasing" : "grid-canvas"}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
          />
        </div>

        <aside className="grid-controls">
          <h2 className="grid-section-title">Grid</h2>
          <div className="grid-dims">
            <label className="auth-label" htmlFor="grid-w">
              Width
              <input
                id="grid-w"
                type="number"
                className="auth-input grid-dim-input"
                min={1}
                max={MAX_DIM}
                value={width}
                onChange={(e) => applyDimension("w", e.target.value)}
              />
            </label>
            <label className="auth-label" htmlFor="grid-h">
              Height
              <input
                id="grid-h"
                type="number"
                className="auth-input grid-dim-input"
                min={1}
                max={MAX_DIM}
                value={height}
                onChange={(e) => applyDimension("h", e.target.value)}
              />
            </label>
          </div>

          <h2 className="grid-section-title">Palette</h2>
          <div className="palette">
            {palette.map((color, i) => (
              <div
                key={i}
                className={
                  !erasing && i === activeColor ? "palette-swatch active" : "palette-swatch"
                }
              >
                <input
                  type="color"
                  value={color}
                  onChange={(e) => updatePaletteColor(i, e.target.value)}
                  onClick={() => {
                    setActiveColor(i);
                    setErasing(false);
                  }}
                  aria-label={`Color ${i + 1}`}
                />
                {palette.length > 1 && (
                  <button
                    type="button"
                    className="palette-remove"
                    aria-label={`Remove color ${i + 1}`}
                    onClick={() => removeColor(i)}
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
            {palette.length < MAX_COLORS && (
              <button type="button" className="palette-add" onClick={addColor} aria-label="Add color">
                +
              </button>
            )}
          </div>

          <div className="grid-tools">
            <button
              type="button"
              className={erasing ? "btn-ghost tool-active" : "btn-ghost"}
              onClick={() => setErasing((e) => !e)}
              aria-pressed={erasing}
            >
              <i className="ti ti-eraser" aria-hidden="true"></i> Eraser
            </button>
          </div>

          <h2 className="grid-section-title">From an image</h2>
          <label className="auth-label" htmlFor="grid-detail">
            Detail — {detail}×{detail} max
          </label>
          <input
            id="grid-detail"
            type="range"
            className="progress-slider grid-slider"
            min={8}
            max={MAX_DIM}
            step={1}
            value={detail}
            onChange={(e) => setDetail(Number(e.target.value))}
          />
          <label className="auth-label" htmlFor="grid-colors">
            Colors — {colorCount}
          </label>
          <input
            id="grid-colors"
            type="range"
            className="progress-slider grid-slider"
            min={2}
            max={MAX_COLORS}
            step={1}
            value={colorCount}
            onChange={(e) => setColorCount(Number(e.target.value))}
          />
          <button type="button" className="btn-primary grid-upload" onClick={() => fileRef.current?.click()}>
            Upload image
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            onChange={handleImageUpload}
            style={{ display: "none" }}
          />
          <p className="grid-hint">
            The image is downsampled to the grid and quantized to your chosen number of colors.
            Higher detail and more colors = clearer, but harder to stitch.
          </p>
        </aside>
      </div>
    </section>
  );
}
