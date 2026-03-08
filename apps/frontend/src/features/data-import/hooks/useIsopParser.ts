import { useCallback, useRef, useState } from 'react';
import type { ParseError, ParseResult } from '../../../domain/isopClientParser';
import { parseISOPFile } from '../../../domain/isopClientParser';
import type { NikufraData } from '../../../domain/nikufra-types';
import { invalidateScheduleCache } from '../../../hooks/useScheduleData';
import type { LoadMeta } from '../../../stores/useDataStore';
import { useDataActions, useDataStore, useNikufraData } from '../../../stores/useDataStore';
import { useSettingsStore } from '../../../stores/useSettingsStore';

export type UploadState =
  | { step: 'idle' }
  | { step: 'processing'; fileName: string }
  | { step: 'preview'; data: NikufraData; meta: LoadMeta; fileName: string }
  | { step: 'error'; errors: string[]; fileName: string };

export const SEMANTICS_OPTIONS: { value: string; label: string }[] = [
  { value: 'raw_np', label: 'Posicao liquida bruta (padrao)' },
  { value: 'cumulative_np', label: 'Posicao liquida cumulativa' },
  { value: 'daily', label: 'Quantidade diaria' },
];

export function useIsopParser() {
  const nikufraData = useNikufraData();
  const loadedAt = useDataStore((s) => s.loadedAt);
  const storedFileName = useDataStore((s) => s.fileName);
  const storedMeta = useDataStore((s) => s.meta);
  const { setNikufraData, clearData } = useDataActions();

  const semantics = useSettingsStore((s) => s.demandSemantics);

  const [uploadState, setUploadState] = useState<UploadState>({ step: 'idle' });
  const [dragActive, setDragActive] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const hasData = nikufraData !== null;

  const processFile = useCallback(
    async (file: File) => {
      setUploadState({ step: 'processing', fileName: file.name });
      try {
        const buffer = await file.arrayBuffer();
        const result = parseISOPFile(buffer, semantics);
        if (result.success) {
          const r = result as ParseResult;
          setUploadState({ step: 'preview', data: r.data, meta: r.meta, fileName: file.name });
        } else {
          const e = result as ParseError;
          setUploadState({ step: 'error', errors: e.errors, fileName: file.name });
        }
      } catch (err) {
        setUploadState({
          step: 'error',
          errors: [err instanceof Error ? err.message : 'Erro desconhecido ao processar ficheiro.'],
          fileName: file.name,
        });
      }
    },
    [semantics],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragActive(false);
      const file = e.dataTransfer.files[0];
      if (file) processFile(file);
    },
    [processFile],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) processFile(file);
      if (fileRef.current) fileRef.current.value = '';
    },
    [processFile],
  );

  const handleApply = useCallback(async () => {
    if (uploadState.step !== 'preview') return;
    await setNikufraData(uploadState.data, uploadState.fileName, uploadState.meta);
    invalidateScheduleCache();
    setUploadState({ step: 'idle' });
  }, [uploadState, setNikufraData]);

  const handleClear = useCallback(() => {
    clearData();
    invalidateScheduleCache();
    setUploadState({ step: 'idle' });
  }, [clearData]);

  return {
    uploadState,
    setUploadState,
    dragActive,
    setDragActive,
    fileRef,
    hasData,
    nikufraData,
    loadedAt,
    storedFileName,
    storedMeta,
    handleDrop,
    handleFileInput,
    handleApply,
    handleClear,
  };
}
