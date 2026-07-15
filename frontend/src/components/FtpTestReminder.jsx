import { useEffect, useState } from "react";
import { api } from "../api";

export default function FtpTestReminder() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    api.ftpTestStatus().then(setStatus).catch(() => {});
  }, []);

  if (!status) return null;

  // Ready to test is the only state worth an attention-grabbing colour; being
  // merely due (but not today) is information, not a call to action.
  const tone = status.ready_today ? "badge-good" : status.due ? "badge-warning" : "badge-muted";

  return (
    <div className={`ftp-reminder ${tone}`}>
      <strong>{status.ready_today ? "Good day to test" : status.due ? "FTP test overdue" : "FTP test"}</strong>{" "}
      {status.message}
    </div>
  );
}
