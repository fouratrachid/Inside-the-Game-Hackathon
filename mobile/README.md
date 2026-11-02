# Touchline+ mobile (Expo second screen)

A TypeScript Expo app that follows a Touchline+ replay on your phone: pick a match, watch the score and the momentum chart update over Server-Sent Events, read momentum-shift notes, and ask the match a question. It talks to the same FastAPI server as the web app and sends only the replay's `session_id` with questions — the server builds the context.

## Run it
Start the server on your computer (`pipenv run dev`, or the Docker image), then:

```bash
cd mobile && npm install
```

```bash
EXPO_PUBLIC_API_URL=http://YOUR-COMPUTER-LAN-IP:8000 npx expo start
```

Scan the QR code with Expo Go. `localhost` only works in a simulator on the same machine. Use `GAME_SOURCE=synthetic` or `both` on the server for the offline synthetic match.

## Check it

```bash
npx tsc --noEmit
```

```bash
npx jest
```

## Structure
| Path | Role |
| --- | --- |
| `App.tsx` | screens: match picker → live view (scoreboard, momentum, shifts, chat) |
| `src/useReplay.ts` | `react-native-sse` subscription → reducer |
| `src/state.ts` | pure replay reducer (match, update, momentum_shift, complete, error, reset) |
| `src/api.ts` | `/matches`, `/chat` (session id only), stream URL |
| `src/components/*` | `MatchPicker`, `Scoreboard`, `MomentumChart` (react-native-svg), `ShiftNotes`, `ChatPanel` |
| `__tests__/*` | Jest + React Native Testing Library (fetch and EventSource mocked) |

Built on Touchline by Hadi Sotudeh (MIT). Data: Hudl StatsBomb open data or a fictional synthetic match.
