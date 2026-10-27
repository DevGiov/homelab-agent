import { http } from './http';

interface ImageUploadResponse {
  url: string;
  data_url: string;
  filename: string;
  width?: number;
  height?: number;
}

function uploadImage(file: File): Promise<ImageUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return http.post('/upload', formData);
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = (err) => reject(err);
    reader.readAsDataURL(file);
  });
}

/**
 * Riconosce se un file è di tipo immagine verificando il MIME type
 * o l'estensione del nome file (fondamentale per iOS che spesso passa MIME vuoto).
 */
export function isImageFile(file: File): boolean {
  if (file.type && file.type.startsWith('image/')) return true;
  return /\.(png|jpe?g|webp|gif|bmp|heic|heif|tiff?)$/i.test(file.name);
}

/**
 * Ottimizza e converte un'immagine prima dell'invio al modello multimodale:
 * 1. Prova prima la decodifica in-browser con createImageBitmap o Image element.
 * 2. Se ha successo, downscala l'immagine a max 1920px sul lato maggiore e la esporta
 *    come JPEG a qualità 0.85 (riducendo foto da 15MB a ~200-400KB ed evitando memory leak su iOS).
 * 3. Se la decodifica in-browser fallisce (es. formato HEIC non supportato dal browser),
 *    invia il file all'endpoint backend /v1/upload (che usa pillow-heif) per transcodificarlo in JPEG.
 */
export async function optimizeAndConvertImage(file: File): Promise<{ dataUrl: string; name: string }> {
  const isHeic = /\.(heic|heif)$/i.test(file.name) || file.type.includes('heic') || file.type.includes('heif');
  const isPng = file.type === 'image/png' || /\.png$/i.test(file.name);

  // Se è un piccolo PNG (< 1.5MB), lasciamo intatta la trasparenza e usiamo fileToDataUrl
  if (isPng && !isHeic && file.size < 1.5 * 1024 * 1024) {
    try {
      const dataUrl = await fileToDataUrl(file);
      return { dataUrl, name: file.name };
    } catch {
      // Procedi con decodifica canvas
    }
  }

  // 1. Prova decodifica nativa in-browser (createImageBitmap o HTMLImageElement)
  try {
    let bitmap: ImageBitmap | HTMLImageElement | null = null;
    let width = 0;
    let height = 0;

    if (typeof createImageBitmap === 'function') {
      try {
        bitmap = await createImageBitmap(file);
        width = bitmap.width;
        height = bitmap.height;
      } catch {
        bitmap = null;
      }
    }

    if (!bitmap) {
      const url = URL.createObjectURL(file);
      try {
        const img = new Image();
        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve();
          img.onerror = () => reject(new Error('Failed to load image element'));
          img.src = url;
        });
        bitmap = img;
        width = img.naturalWidth || img.width;
        height = img.naturalHeight || img.height;
      } finally {
        URL.revokeObjectURL(url);
      }
    }

    if (bitmap && width > 0 && height > 0) {
      const MAX_DIM = 1600;
      let targetW = width;
      let targetH = height;

      if (targetW > MAX_DIM || targetH > MAX_DIM) {
        if (targetW > targetH) {
          targetH = Math.round((targetH * MAX_DIM) / targetW);
          targetW = MAX_DIM;
        } else {
          targetW = Math.round((targetW * MAX_DIM) / targetH);
          targetH = MAX_DIM;
        }
      }

      const canvas = document.createElement('canvas');
      canvas.width = targetW;
      canvas.height = targetH;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        // Sfondo bianco per preservare contrasto se c'era trasparenza
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, targetW, targetH);
        ctx.drawImage(bitmap, 0, 0, targetW, targetH);

        const dataUrl = canvas.toDataURL('image/jpeg', 0.80);

        if ('close' in bitmap && typeof (bitmap as ImageBitmap).close === 'function') {
          (bitmap as ImageBitmap).close();
        }

        const cleanName = file.name.replace(/\.(heic|heif)$/i, '.jpg');
        return { dataUrl, name: cleanName };
      }
    }
  } catch (clientErr) {
    console.warn("Decodifica client-side non riuscita, ricorso all'upload backend:", clientErr);
  }

  // 2. Fallback backend: usa /v1/upload con pillow-heif
  try {
    const uploadRes = await uploadImage(file);
    return { dataUrl: uploadRes.data_url, name: uploadRes.filename };
  } catch (uploadErr) {
    console.error("Anche l'upload backend è fallito:", uploadErr);
    // Ultima spiaggia: lettura diretta FileReader
    const rawDataUrl = await fileToDataUrl(file);
    return { dataUrl: rawDataUrl, name: file.name };
  }
}
