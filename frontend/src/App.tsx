import { useEffect, useState } from 'react';
import Home from './components/Home';
import Workspace from './components/Workspace';
import { Toaster } from './components/ui';

function readRoute(): number | null {
  const m = window.location.hash.match(/^#\/drawings\/(\d+)/);
  return m ? Number(m[1]) : null;
}

export default function App() {
  const [drawingId, setDrawingId] = useState<number | null>(readRoute);

  useEffect(() => {
    const onHash = () => setDrawingId(readRoute());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const open = (id: number) => { window.location.hash = `#/drawings/${id}`; };
  const back = () => { window.location.hash = ''; };

  return (
    <>
      {drawingId === null ? <Home onOpen={open} /> : <Workspace key={drawingId} id={drawingId} onBack={back} />}
      <Toaster />
    </>
  );
}
