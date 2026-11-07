import SwiftUI

// Screens that M1 (NewChatView/NewTopicView) and M3 (ChatInfoView) replace. Delete the matching type here when yours lands.

/// New chat, step 1: where should it go?
struct NewChatView: View {
    @Environment(AppModel.self) private var model
    @State private var selected: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Eyebrow(text: "NEW CONVERSATION")
            Text("Where should it go?").themeFont(26, .semibold)
            Text("Pick the workspace for this topic.").themeFont(14).foregroundStyle(Theme.muted)
            ScrollView {
                VStack(spacing: 8) {
                    ForEach(model.workspaces) { w in
                        Button { selected = w.id } label: {
                            HStack(spacing: 12) {
                                Avatar(name: w.displayName, size: 38)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(w.displayName).themeFont(16, .semibold)
                                    Text(lastSeenText(w.lastSeen, online: w.online)).themeFont(12).foregroundStyle(Theme.muted)
                                }
                                Spacer()
                                Image(systemName: selected == w.id ? "largecircle.fill.circle" : "circle").foregroundStyle(selected == w.id ? Theme.brand : Theme.muted)
                            }.padding(12).background(Theme.surface, in: RoundedRectangle(cornerRadius: 12))
                                .overlay(RoundedRectangle(cornerRadius: 12).stroke(selected == w.id ? Theme.brand : Theme.border))
                                .contentShape(Rectangle())
                        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("pick-\(w.id)")
                    }
                }
            }
            Button {
                if let selected { model.path.append(.newTopic(selected)) }
            } label: { Text("Continue") }.buttonStyle(PrimaryButtonStyle(muted: selected == nil)).disabled(selected == nil).accessibilityIdentifier("pick-continue")
        }.padding(16).background(Theme.bg.ignoresSafeArea()).navigationTitle("New chat").navigationBarTitleDisplayMode(.inline)
            .onAppear { if model.workspaces.count == 1 { selected = model.workspaces.first?.id } }
    }
}

/// New chat, step 2: the first message. The workspace answers with a ticket.
struct NewTopicView: View {
    @Environment(AppModel.self) private var model
    let workspaceId: String
    @State private var text = ""
    @State private var sending = false
    @State private var voice: VoiceInput?
    @FocusState private var focused: Bool

    var body: some View {
        let name = model.workspace(workspaceId)?.displayName ?? "Workspace"
        let mic = MicInput(voice: voice)
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) { Avatar(name: name, size: 30); Text(name).themeFont(14).foregroundStyle(Theme.muted) }
            TextField(mic.recording ? "Recording your voice…" : mic.transcribing ? "Writing it down…" : "What do you need?", text: $text, axis: .vertical)
                .lineLimit(5...12).focused($focused).themeFont(17).disabled(mic.busy || sending)
                .padding(14).background(Theme.surface, in: RoundedRectangle(cornerRadius: 14)).overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.borderStrong))
                .accessibilityIdentifier("topic-field")
            HStack(spacing: 10) {
                MicButton(voice: voice, text: $text, disabled: sending)
                Text(voice?.error ?? mic.label).themeFont(12, .medium).foregroundStyle(voice?.error != nil ? Theme.danger : Theme.muted)
                    .accessibilityIdentifier("mic-status")
            }
            Spacer()
            let ok = !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !sending && !mic.busy
            Button { sending = true; Task { await model.startTopic(workspaceId: workspaceId, text: text); sending = false } } label: { Text(sending ? "Starting…" : "Start") }
                .buttonStyle(PrimaryButtonStyle(muted: !ok)).disabled(!ok).accessibilityIdentifier("topic-start")
            Text("This starts a new ticket. You get a message when there is a result, a question or a problem.").themeFont(12).foregroundStyle(Theme.muted)
        }.padding(16).background(Theme.bg.ignoresSafeArea()).navigationTitle("New topic in \(name)").navigationBarTitleDisplayMode(.inline)
            .onAppear { if !UserDefaults.standard.bool(forKey: "autoMic") { focused = true } }
            .task {
                if voice == nil { voice = MicInput.make(model) }
                if UserDefaults.standard.bool(forKey: "autoMic") { await voice?.toggle(current: text) }
            }
            .onChange(of: voice?.transcript) { _, t in if let t { text = t } }
            .onDisappear { voice?.stop() }
    }
}

/// Chat info: details and the media, links and files kept with a ticket (or the whole workspace).
struct ChatInfoView: View {
    @Environment(AppModel.self) private var model
    let workspaceId: String
    let ticketId: String?
    @State private var tab = 0

    var body: some View {
        let w = model.workspace(workspaceId)
        let t = ticketId.flatMap { model.ticket(workspaceId, $0) }
        let wsTickets = model.tickets.filter { $0.workspace == workspaceId && $0.ticket != nil }
        let atts: [TicketSnapshot.Attachment] = (t.map { [$0] } ?? wsTickets).flatMap { $0.view?.attachments ?? [] }
        let media = atts.filter { $0.kind == "image" }, links = atts.filter { $0.kind == "link" }, files = atts.filter { $0.kind == "file" }
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let t {
                    Text(t.displayTitle).themeFont(24, .semibold)
                    HStack { KeyTag(key: t.key); StatusPill(status: t.status, kind: t.kind) }
                    if let a = t.view?.agent { detail("Agent", a) }
                    detail("Workspace", w?.displayName ?? t.workspaceName)
                    detail("Updated", ChatBuilder.timeText(t.at))
                    if let s = t.view?.summary ?? Optional(t.text), !s.isEmpty {
                        VStack(alignment: .leading, spacing: 4) { Eyebrow(text: "WHERE IT STANDS"); Text(s).themeFont(15) }
                            .padding(.leading, 12).overlay(alignment: .leading) { Rectangle().fill(Theme.brand).frame(width: 3) }
                    }
                } else {
                    Avatar(name: w?.displayName ?? "W", size: 52)
                    Text(w?.displayName ?? "Workspace").themeFont(24, .semibold)
                    Text(w.map { lastSeenText($0.lastSeen, online: $0.online) } ?? "").themeFont(14).foregroundStyle(Theme.muted)
                    if let d = w?.description { Text(d).themeFont(15) }
                    Eyebrow(text: "\(wsTickets.count) TICKETS")
                    ForEach(wsTickets) { x in
                        HStack(spacing: 8) { KeyTag(key: x.key); Text(x.displayTitle).themeFont(14).lineLimit(1); Spacer(); StatusPill(status: x.status, kind: x.kind) }
                    }
                }
                Picker("", selection: $tab) {
                    Text("Media \(media.count)").tag(0); Text("Links \(links.count)").tag(1); Text("Files \(files.count)").tag(2)
                }.pickerStyle(.segmented).accessibilityIdentifier("info-tabs")
                let shown = [media, links, files][tab]
                if shown.isEmpty { Text("Nothing here yet.").themeFont(14).foregroundStyle(Theme.muted) }
                else if tab == 0 {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: 8)], spacing: 8) { ForEach(shown) { AttachmentTile(attachment: $0) } }
                } else {
                    ForEach(shown) { AttachmentTile(attachment: $0).padding(.vertical, 4) }
                }
            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
        }.background(Theme.bg.ignoresSafeArea()).navigationTitle("Chat info").navigationBarTitleDisplayMode(.inline)
    }

    private func detail(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) { Text(label).themeFont(12).foregroundStyle(Theme.muted); Text(value).themeFont(15) }
    }
}

/// The mic of every composer: tap to record, tap to stop, the transcript lands in the text field to edit before Send.
/// `autoMic` (a setting) starts recording when the composer opens. Wording and labels as the old Send screen had them.
@MainActor struct MicInput {
    var voice: VoiceInput?
    var recording: Bool { voice?.isRecording == true }
    var transcribing: Bool { voice?.isTranscribing == true }
    var busy: Bool { recording || transcribing }
    var label: String { recording ? "Recording your voice… tap to stop" : transcribing ? "Writing it down…" : "Tap to speak" }

    static func make(_ model: AppModel) -> VoiceInput { VoiceInput(mode: model.voiceMode, transcribe: { try await model.transcribe($0) }) }
}

struct MicButton: View {
    let voice: VoiceInput?
    @Binding var text: String
    var disabled = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var toggling = false

    var body: some View {
        let m = MicInput(voice: voice)
        Button {
            toggling = true
            Task { await voice?.toggle(current: text); toggling = false }
        } label: {
            Image(systemName: m.recording ? "stop.fill" : "mic.fill").font(.system(size: 18, weight: .semibold))
                .foregroundStyle(m.recording ? Theme.danger : Theme.brand)
                .frame(width: 44, height: 44)
                .background((m.recording ? Theme.danger : Theme.brand).opacity(0.1), in: Circle())
                .overlay(Circle().stroke((m.recording ? Theme.danger : Theme.brand).opacity(m.recording ? 0.7 : 0.3), lineWidth: m.recording ? 2 : 1))
                .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: m.recording)
        }.buttonStyle(.plain).accessibilityIdentifier("mic").accessibilityLabel(m.label)
            .disabled(voice == nil || toggling || m.transcribing || disabled)
    }
}

