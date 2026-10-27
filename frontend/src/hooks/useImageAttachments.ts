import { useCallback, useEffect, useState, type DragEvent } from 'react';
import { isImageFile, optimizeAndConvertImage } from '../api/uploads';

export interface PendingImage {
  id: string;
  dataUrl: string;
  name: string;
}

/** Immagini da allegare al prossimo messaggio: file picker, incolla (Ctrl+V) e drag & drop. */
export function useImageAttachments() {
  const [images, setImages] = useState<PendingImage[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const addFiles = useCallback(async (files: FileList | File[]) => {
    const valid = Array.from(files).filter(isImageFile);
    if (valid.length === 0) return;

    setIsProcessing(true);
    const added: PendingImage[] = [];
    for (const file of valid) {
      try {
        const { dataUrl, name } = await optimizeAndConvertImage(file);
        added.push({ id: `img_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, dataUrl, name });
      } catch (err) {
        console.warn('Immagine non leggibile:', err);
      }
    }
    setIsProcessing(false);
    if (added.length > 0) setImages((prev) => [...prev, ...added]);
  }, []);

  useEffect(() => {
    const handlePaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.items ?? [])
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null && isImageFile(file));
      if (files.length > 0) addFiles(files);
    };
    window.addEventListener('paste', handlePaste);
    return () => window.removeEventListener('paste', handlePaste);
  }, [addFiles]);

  const stop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const dropZoneProps = {
    onDragOver: (e: DragEvent) => {
      stop(e);
      setIsDragging(true);
    },
    onDragLeave: (e: DragEvent) => {
      stop(e);
      setIsDragging(false);
    },
    onDrop: (e: DragEvent) => {
      stop(e);
      setIsDragging(false);
      if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
    },
  };

  return {
    images,
    isProcessing,
    isDragging,
    dropZoneProps,
    addFiles,
    remove: (id: string) => setImages((prev) => prev.filter((img) => img.id !== id)),
    clear: () => setImages([]),
  };
}

export type ImageAttachments = ReturnType<typeof useImageAttachments>;
