import { lazy, useCallback, useState, useEffect, useRef } from 'react';
import { ThreadList } from './ThreadList';
import { Chat } from './components/chat/Chat';
import { ToolLog } from './ToolLog';
import { useThreads } from './hooks/useThreads';
import { useChat } from './hooks/useChat';
import { navigate, useRoute } from './hooks/useRoute';
import { documentTitle, formatRoute, HOME, viewRoute, type AppView, type Route } from './utils/route';
import { useDiagnosticsPanel } from './hooks/useDiagnosticsPanel';
import { useMediaQuery } from './hooks/useMediaQuery';
import { useModalFocus } from './hooks/useModalFocus';
import { ThemeProvider } from './theme/ThemeContext';
import { AmbientBackground } from './components/AmbientBackground';
import { ErrorBoundary } from './components/ErrorBoundary';
import { LazyBoundary } from './components/LazyBoundary';

const AutomationsView = lazy(() =>
  import('./components/automations/AutomationsView').then((m) => ({ default: m.AutomationsView })),
);
const CalendarView = lazy(() =>
  import('./components/calendar/CalendarView').then((m) => ({ default: m.CalendarView })),
);
const MemoryView = lazy(() =>
  import('./components/memory/MemoryView').then((m) => ({ default: m.MemoryView })),
);
const MetricsView = lazy(() =>
  import('./components/metrics/MetricsView').then((m) => ({ default: m.MetricsView })),
);

function MainLayout() {
  const route = useRoute();
  const currentView = route.view;
  const {
    threads,
    isLoadingThreads,
    isBackendHealthy,
    error: threadError,
    setError: setThreadError,
    loadThreads,
    registerThread,
    isMissingThread,
    deleteThread,
    deleteAllThreads,
  } = useThreads();

  // Conversazione della chat: quella della URL. Sulle altre viste resta l'ultima aperta, così "Chat" ci torna e lo stream
  // in corso non si ricarica. Una che non esiste più (eliminata, o un link vecchio) vale come una conversazione nuova.
  const urlThreadId = route.view === 'chat' ? route.threadId : null;
  const isUrlThreadMissing = urlThreadId !== null && isMissingThread(urlThreadId);
  const [lastChatThreadId, setLastChatThreadId] = useState<string | null>(urlThreadId);
  if (route.view === 'chat' && lastChatThreadId !== urlThreadId) setLastChatThreadId(urlThreadId);
  const shownThreadId = route.view === 'chat' ? urlThreadId : lastChatThreadId;
  const currentThreadId = shownThreadId !== null && isMissingThread(shownThreadId) ? null : shownThreadId;

  // La URL di una conversazione che non c'è torna alla pagina iniziale senza lasciare la voce morta nella cronologia
  useEffect(() => {
    if (isUrlThreadMissing) navigate(HOME, { replace: true });
  }, [isUrlThreadMissing]);

  // Il primo messaggio dà l'id alla conversazione nuova: / diventa /c/<id> al posto della voce corrente, così
  // indietro non riporta a una chat vuota
  const handleThreadCreated = useCallback(
    (threadId: string) => {
      registerThread(threadId);
      navigate({ view: 'chat', threadId }, { replace: true });
    },
    [registerThread],
  );

  const {
    currentMessages,
    currentThreadTitle,
    threadLevel,
    setThreadLevel,
    isLoadingChat,
    isPaused,
    chatError,
    setChatError,
    handleSendMessage,
    handleRegenerateMessage,
    handleEditPrompt,
    handleSwitchVersion,
    handleStop,
    handlePause,
    handleResume,
    loadThreadHistory,
    handleApprovalResolved,
    diagnostics,
  } = useChat(currentThreadId, handleThreadCreated);

  // Dove porta ogni vista: la chat riapre l'ultima conversazione
  const routeForView = (view: AppView): Route => (view === 'chat' ? { view, threadId: currentThreadId } : viewRoute(view));
  const openThread = (threadId: string) => {
    setThreadError(null);
    navigate({ view: 'chat', threadId });
  };

  // Link markdown #event-<uid>: il calendario con l'evento, come posto nuovo nella cronologia
  useEffect(() => {
    const handleOpenEvent = (e: Event) => {
      const eventUid = (e as CustomEvent<{ eventUid?: string }>).detail?.eventUid;
      if (eventUid) navigate({ view: 'calendar', eventUid });
    };
    window.addEventListener('open-calendar-event', handleOpenEvent);
    return () => window.removeEventListener('open-calendar-event', handleOpenEvent);
  }, []);

  // Titolo della scheda: il posto, con il titolo della conversazione appena si conosce
  const threadTitle = currentThreadTitle || threads.find((t) => t.thread_id === currentThreadId)?.title;
  useEffect(() => {
    document.title = documentTitle(route.view === 'chat' ? { view: 'chat', threadId: currentThreadId } : route, threadTitle);
  }, [route, currentThreadId, threadTitle]);

  // Mobile Drawers Navigation state
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState<boolean>(false);
  const [isMobileToolLogOpen, setIsMobileToolLogOpen] = useState<boolean>(false);
  const diagnosticsPanel = useDiagnosticsPanel();
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);

  // Sotto `md` le barre laterali sono cassetti fuori schermo: chiusi sono `inert` (fuori dal Tab e dagli screen reader),
  // aperti tengono il focus come una finestra modale. Da `md` in su sono sempre visibili e interattive.
  const isDesktop = useMediaQuery('(min-width: 768px)', true);
  const sidebarRef = useRef<HTMLDivElement>(null);
  const toolLogRef = useRef<HTMLDivElement>(null);
  useModalFocus(sidebarRef, { active: !isDesktop && isMobileSidebarOpen, onClose: () => setIsMobileSidebarOpen(false) });
  useModalFocus(toolLogRef, { active: !isDesktop && isMobileToolLogOpen, onClose: () => setIsMobileToolLogOpen(false) });

  // Passando a uno schermo largo i cassetti si chiudono: tornando stretti non riappaiono aperti
  useEffect(() => {
    if (!isDesktop) return;
    setIsMobileSidebarOpen(false);
    setIsMobileToolLogOpen(false);
  }, [isDesktop]);

  // Cambiando posto, anche con indietro e avanti del browser, i cassetti si chiudono: la cronologia ha solo i posti
  const routeUrl = formatRoute(route);
  useEffect(() => {
    setIsMobileSidebarOpen(false);
    setIsMobileToolLogOpen(false);
  }, [routeUrl]);

  // Reset selected message when thread changes
  useEffect(() => {
    setSelectedMessageId(null);
  }, [currentThreadId]);

  const activeError = threadError || chatError;
  const clearErrors = () => {
    setThreadError(null);
    setChatError(null);
  };

  return (
    <div className="flex h-dvh w-screen bg-bg text-fg overflow-hidden font-sans relative transition-colors duration-300">
      {/* Ambient Animated Glow Background (behind all glass panels) */}
      <AmbientBackground />

      {/* Mobile Backdrop Overlay */}
      {(isMobileSidebarOpen || isMobileToolLogOpen) && (
        <div
          onClick={() => {
            setIsMobileSidebarOpen(false);
            setIsMobileToolLogOpen(false);
          }}
          className="fixed inset-0 bg-bg/80 backdrop-blur-md z-40 md:hidden transition-opacity duration-300"
        />
      )}

      {/* Left Sidebar: Threads & Navigation (Responsive Drawer) */}
      <div
        ref={sidebarRef}
        inert={!isDesktop && !isMobileSidebarOpen}
        className={`fixed md:relative inset-y-0 left-0 z-50 md:z-auto transform ${
          isMobileSidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        } transition-transform duration-300 ease-in-out flex shrink-0`}
      >
        <ThreadList
          threads={threads}
          currentThreadId={currentThreadId}
          onSelectThread={(id) => {
            openThread(id);
            setIsMobileSidebarOpen(false);
          }}
          onNewThread={() => {
            setThreadError(null);
            navigate(HOME);
            setIsMobileSidebarOpen(false);
          }}
          onDeleteThread={deleteThread}
          onDeleteAllThreads={deleteAllThreads}
          onRefresh={() => {
            loadThreads();
            if (currentThreadId) loadThreadHistory(currentThreadId);
          }}
          isLoading={isLoadingThreads}
          isBackendHealthy={isBackendHealthy}
          onCloseMobile={() => setIsMobileSidebarOpen(false)}
          currentView={currentView}
          viewHref={(v) => formatRoute(routeForView(v))}
          onViewChange={(v) => {
            navigate(routeForView(v));
            setIsMobileSidebarOpen(false);
          }}
        />
      </div>

      {/* Area centrale: la chat o una delle viste, l'unico <main> della pagina */}
      <main className="flex-1 min-w-0 flex">
        {/* Il titolo dell'app sta qui e non nella barra laterale: su mobile, chiusa, è inert e il titolo sparirebbe con lei */}
        <h1 className="sr-only">Main-Agent UI</h1>
        {currentView === 'chat' ? (
          <Chat
            currentThreadId={currentThreadId}
            currentThreadTitle={currentThreadTitle}
            threadLevel={threadLevel}
            onThreadLevelSaved={setThreadLevel}
            messages={currentMessages}
            onSendMessage={handleSendMessage}
            onRegenerate={handleRegenerateMessage}
            onEditPrompt={handleEditPrompt}
            onSwitchVersion={handleSwitchVersion}
            onStop={handleStop}
            onPause={handlePause}
            onResume={handleResume}
            onApprovalResolved={handleApprovalResolved}
            isPaused={isPaused}
            isLoading={isLoadingChat}
            error={activeError}
            onClearError={clearErrors}
            onOpenMobileSidebar={() => setIsMobileSidebarOpen(true)}
            onOpenMobileToolLog={() => {
              diagnosticsPanel.reveal();
              setIsMobileToolLogOpen(true);
            }}
            onInspectMessage={(msgId) => {
              setSelectedMessageId(msgId);
              diagnosticsPanel.reveal();
              setIsMobileToolLogOpen(true);
            }}
          />
        ) : currentView === 'automations' ? (
          <LazyBoundary title="Errore nella vista automazioni">
            <AutomationsView onOpenMobileSidebar={() => setIsMobileSidebarOpen(true)} />
          </LazyBoundary>
        ) : currentView === 'memory' ? (
          <LazyBoundary title="Errore nella vista memoria">
            <MemoryView
              threads={threads}
              onOpenThread={openThread}
              onOpenMobileSidebar={() => setIsMobileSidebarOpen(true)}
            />
          </LazyBoundary>
        ) : currentView === 'metrics' ? (
          <LazyBoundary title="Errore nella vista metriche">
            <MetricsView onOpenMobileSidebar={() => setIsMobileSidebarOpen(true)} />
          </LazyBoundary>
        ) : (
          <LazyBoundary title="Errore nella vista calendario">
            <CalendarView
              initialEventUid={route.view === 'calendar' ? route.eventUid : null}
              onClearInitialEvent={() => navigate(viewRoute('calendar'), { replace: true })}
              onOpenMobileSidebar={() => setIsMobileSidebarOpen(true)}
            />
          </LazyBoundary>
        )}
      </main>

      {/* Right Sidebar: Tool & Plan Log (Responsive Drawer), solo nella chat */}
      {currentView === 'chat' && (
        <div
          ref={toolLogRef}
          inert={!isDesktop && !isMobileToolLogOpen}
          className={`fixed md:relative inset-y-0 right-0 z-50 md:z-auto transform ${
            isMobileToolLogOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0'
          } transition-transform duration-300 ease-in-out flex shrink-0`}
        >
          <ToolLog
            toolUsed={diagnostics.activeTool}
            planSteps={diagnostics.activePlan}
            planStructure={diagnostics.activePlanStructure}
            executionTrace={diagnostics.activeExecutionTrace}
            rollbackTrace={diagnostics.activeRollbackTrace}
            mode={diagnostics.activeMode}
            webPrefetch={diagnostics.activeWebPrefetch}
            currentThreadId={currentThreadId}
            isOpen={diagnosticsPanel.open}
            onToggle={diagnosticsPanel.toggle}
            onCloseMobile={() => setIsMobileToolLogOpen(false)}
            messages={currentMessages}
            selectedMessageId={selectedMessageId}
            onSelectMessageId={setSelectedMessageId}
          />
        </div>
      )}
    </div>
  );
}


export function App() {
  return (
    <ErrorBoundary title="Errore nell'applicazione">
      <ThemeProvider>
        <MainLayout />
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
