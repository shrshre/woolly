// Image-to-grid conversion: downsample to grid dimensions, then median-cut
// color quantization to a small palette (the "clarity" controls).

export type RGB = [number, number, number];

export function rgbToHex([r, g, b]: RGB): string {
  const part = (v: number) => v.toString(16).padStart(2, "0");
  return `#${part(r)}${part(g)}${part(b)}`;
}

/** Median-cut quantization: reduce a pixel list to `count` representative colors. */
export function medianCut(pixels: RGB[], count: number): RGB[] {
  if (pixels.length === 0) return [];

  type Bucket = RGB[];
  const buckets: Bucket[] = [pixels];

  const channelRange = (bucket: Bucket, ch: number) => {
    let min = 255;
    let max = 0;
    for (const px of bucket) {
      if (px[ch] < min) min = px[ch];
      if (px[ch] > max) max = px[ch];
    }
    return max - min;
  };

  while (buckets.length < count) {
    // Split the bucket with the widest channel range
    let bestIdx = -1;
    let bestRange = -1;
    let bestChannel = 0;
    buckets.forEach((bucket, i) => {
      if (bucket.length < 2) return;
      for (let ch = 0; ch < 3; ch++) {
        const range = channelRange(bucket, ch);
        if (range > bestRange) {
          bestRange = range;
          bestIdx = i;
          bestChannel = ch;
        }
      }
    });
    if (bestIdx === -1) break; // nothing left to split

    const bucket = buckets[bestIdx];
    bucket.sort((a, b) => a[bestChannel] - b[bestChannel]);
    const mid = Math.floor(bucket.length / 2);
    buckets.splice(bestIdx, 1, bucket.slice(0, mid), bucket.slice(mid));
  }

  const averages = buckets.map((bucket): RGB => {
    let r = 0;
    let g = 0;
    let b = 0;
    for (const px of bucket) {
      r += px[0];
      g += px[1];
      b += px[2];
    }
    const n = bucket.length;
    return [Math.round(r / n), Math.round(g / n), Math.round(b / n)];
  });

  // Deduplicate colors that averaged to the same value
  const seen = new Set<string>();
  return averages.filter((rgb) => {
    const key = rgbToHex(rgb);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function nearestIndex(palette: RGB[], px: RGB): number {
  let best = 0;
  let bestDist = Infinity;
  for (let i = 0; i < palette.length; i++) {
    const [r, g, b] = palette[i];
    const dist = (r - px[0]) ** 2 + (g - px[1]) ** 2 + (b - px[2]) ** 2;
    if (dist < bestDist) {
      bestDist = dist;
      best = i;
    }
  }
  return best;
}

export interface GridFromImage {
  width: number;
  height: number;
  cells: (string | null)[];
  palette: string[];
}

/**
 * Convert an image to grid cells: draw it downsampled to width x height,
 * quantize to `colorCount` colors, and map every cell to its nearest color.
 */
export function imageToGrid(
  img: HTMLImageElement,
  maxDim: number,
  colorCount: number
): GridFromImage {
  const aspect = img.naturalWidth / img.naturalHeight;
  const width = Math.max(1, Math.min(50, aspect >= 1 ? maxDim : Math.round(maxDim * aspect)));
  const height = Math.max(1, Math.min(50, aspect >= 1 ? Math.round(maxDim / aspect) : maxDim));

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;
  // White background so transparency doesn't read as black
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  ctx.drawImage(img, 0, 0, width, height);

  const data = ctx.getImageData(0, 0, width, height).data;
  const pixels: RGB[] = [];
  for (let i = 0; i < data.length; i += 4) {
    pixels.push([data[i], data[i + 1], data[i + 2]]);
  }

  const paletteRgb = medianCut([...pixels], colorCount);
  const palette = paletteRgb.map(rgbToHex);
  const cells = pixels.map((px) => palette[nearestIndex(paletteRgb, px)]);

  return { width, height, cells, palette };
}
