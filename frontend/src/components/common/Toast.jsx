import { useEffect } from "react";
import { createPortal } from "react-dom";

export default function Toast({ message, type = "error", onClose }) {
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(onClose, 5000);
    return () => clearTimeout(timer);
  }, [message, onClose]);

  if (!message) return null;

  return createPortal(
    <div className={`toast toast-${type}`} role="alert">
      <span>{message}</span>
      <button className="toast-close" onClick={onClose}>×</button>
    </div>,
    document.body
  );
}
