import { useEffect, useState } from 'react';
import { apiFetch } from '../../lib/api';

export interface ChannelsInfo {
  status: string; // bridge status, or "not_configured"
  channels: string[];
}

export async function fetchChannelsInfo(): Promise<ChannelsInfo> {
  const res = await apiFetch('/v1/channels');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  const raw: unknown[] = Array.isArray(data.channels) ? data.channels : [];
  return {
    status: typeof data.status === 'string' ? data.status : 'not_configured',
    channels: raw.map((c) => (typeof c === 'string' ? c : String((c as { name?: string }).name ?? c))),
  };
}

// Mirrors core/config.py: ChannelConfig + TelegramChannelConfig.
const TELEGRAM_SNIPPET = `[channel]
enabled = true
default_channel = "telegram"

[channel.telegram]
bot_token = "123456:ABC…"     # do @BotFather (ou TELEGRAM_BOT_TOKEN)
allowed_chat_ids = "123456789" # separados por vírgula; só você`;

export function ChannelsView({ info, error }: { info: ChannelsInfo | null; error: string | null }) {
  const connected = info && info.channels.length > 0;
  return (
    <div className="space-y-2">
      <div className="jarvis-row">
        <span className="text-zinc-400 tracking-wider">CANAIS</span>
        <span className={connected ? 'text-emerald-300' : 'text-zinc-500'}>
          {error ? 'ERRO' : !info ? '…' : connected ? info.channels.join(', ') : 'NENHUM'}
        </span>
      </div>
      {!connected && (
        <details className="text-[11px] text-zinc-400">
          <summary className="cursor-pointer text-cyan-300">Falar com o Jarvis pelo Telegram</summary>
          <ol className="list-decimal pl-4 mt-2 space-y-1 leading-relaxed">
            <li>No Telegram, fale com <b>@BotFather</b> → <code>/newbot</code> e copie o token.</li>
            <li>Descubra seu chat id (ex.: fale com <b>@userinfobot</b>).</li>
            <li>
              Adicione ao <code>~/.openjarvis/config.toml</code>:
              <pre className="jarvis-approval-payload mt-1">{TELEGRAM_SNIPPET}</pre>
            </li>
            <li>Reinicie o <code>jarvis serve</code>. Use <code>allowed_chat_ids</code> para que só você consiga comandar o Jarvis.</li>
          </ol>
        </details>
      )}
    </div>
  );
}

/** Settings section: messaging channels status + Telegram setup guide. */
export function HudChannels() {
  const [info, setInfo] = useState<ChannelsInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetchChannelsInfo().then(setInfo).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);
  return <ChannelsView info={info} error={error} />;
}
