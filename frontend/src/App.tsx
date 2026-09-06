import { useState } from 'react';
import { ThreadList } from './ThreadList';
import { Chat } from './Chat';
import { ToolLog } from './ToolLog';
import { useThreads } from './hooks/useThreads';
import { useChat } from './hooks/useChat';
import { ThemeProvider } from './theme/ThemeContext';
import { AmbientBackground } from './components/AmbientBackground';

function MainLayout() {
  const {
    threads,
    currentThreadId,
    isLoadingThreads,
    isBackendHealthy,
    error: threadError,
    setError: setThreadError,
    loadThreads,
    selectThread,
    createNewThread,
    deleteThread,
    deleteAllThreads,
  } = useThreads();

  const {
    currentMessages,
    isLoadingChat,
    chatError,
    setChatError,
    handleSendMessage,
    loadThreadHistory,
    diagnostics,
  } = useChat(currentThreadId, (newId) => selectThread(newId));

  // Mobile Drawers Navigation state
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState<boolean>(false);
  const [isMobileToolLogOpen, setIsMobileToolLogOpen] = useState<boolean>(false);
  const [isToolLogOpen, setIsToolLogOpen] = useState<boolean>(true);

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

      {/* Left Sidebar: Threads (Responsive Drawer) */}
      <div
        className={`fixed md:relative inset-y-0 left-0 z-50 md:z-auto transform ${
          isMobileSidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        } transition-transform duration-300 ease-in-out flex shrink-0`}
      >
        <ThreadList
          threads={threads}
          currentThreadId={currentThreadId}
          onSelectThread={(id) => {
            selectThread(id);
            setIsMobileSidebarOpen(false);
          }}
          onNewThread={() => {
            createNewThread();
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
        />
      </div>

      {/* Main Area: Chat */}
      <Chat
        currentThreadId={currentThreadId}
        messages={currentMessages}
        onSendMessage={handleSendMessage}
        isLoading={isLoadingChat}
        error={activeError}
        onClearError={clearErrors}
        onOpenMobileSidebar={() => setIsMobileSidebarOpen(true)}
        onOpenMobileToolLog={() => setIsMobileToolLogOpen(true)}
      />

      {/* Right Sidebar: Tool & Plan Log (Responsive Drawer) */}
      <div
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
          isOpen={isToolLogOpen}
          onToggle={() => setIsToolLogOpen(!isToolLogOpen)}
          onCloseMobile={() => setIsMobileToolLogOpen(false)}
        />
      </div>
    </div>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <MainLayout />
    </ThemeProvider>
  );
}

export default App;
