import SwiftUI

struct SendView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var voice: VoiceInput?
    @State private var text = ""
    @State private var workspaceID = ""
    @State private var sent: AppModel.SentNote?
    @State private var sending = false
    @State private var toggling = false
    @State private var pulse = false
    @State private var showHint = false
    @FocusState private var editing: Bool
    @Environment(\.dynamicTypeSize) private var typeSize
    private var editorHeight: CGFloat { editing ? 88 : (typeSize.isAccessibilitySize ? 240 : 137) }
    private var hintText: String {
        recording ? "Tap the mic to stop first." : transcribing ? "One moment, writing it down." :
        workspaceID.isEmpty ? "Pick a workspace first." : "Write or say a message first."
    }

    private var recording: Bool { voice?.isRecording == true }
    private var transcribing: Bool { voice?.isTranscribing == true }
    private var micLabel: String { recording ? "Recording your voice… tap to stop" : transcribing ? "Writing it down…" : "Tap to speak" }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if !editing || sent != nil { ScreenHeading(title: "Say it. Send it.", subtitle: "A thought, a request, a next step.").padding(.top, 14) }
                if let sent { sentState(sent) }
                else if model.workspaces.isEmpty && model.message != nil { offlineState }
                else if model.workspaces.isEmpty && model.hasLoaded { emptyState }
                else { composer }
                ModelMessage().padding(.top, 12)
            }.padding(.horizontal, 23).padding(.top, 6).padding(.bottom, 20)
        }
        .scrollDismissesKeyboard(.interactively)
        .toolbar { ToolbarItemGroup(placement: .keyboard) { Spacer(); Button("Done") { editing = false }.accessibilityIdentifier("keyboard-done") } }
        .task {
            if voice == nil { let m = model; voice = VoiceInput(mode: model.voiceMode, transcribe: { try await m.transcribe($0) }) }
            selectWorkspace()
            if UserDefaults.standard.bool(forKey: "autoMic") { await voice?.toggle(current: text) }
        }
        .onChange(of: model.workspaces) { _, _ in selectWorkspace() }
        .onChange(of: model.tab) { _, tab in
            if tab == .send { selectWorkspace(preferFilter: true) }
            else { voice?.stop(); editing = false }
        }
        .onChange(of: voice?.transcript) { _, transcript in
            // A final transcript can arrive in the same update that stops recording.
            if let transcript { text = transcript }
        }
        .onChange(of: recording) { _, active in pulse = active }
        .onDisappear { voice?.stop() }
        .sensoryFeedback(.success, trigger: model.sendTick)
        .sensoryFeedback(.error, trigger: model.errorTick)
        .animation(reduceMotion ? nil : .easeOut(duration: 0.25), value: sent)
    }

    private var offlineState: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Can't load your workspaces").font(Theme.font(15, .semibold))
            Text("Check your connection, then try again. You can send a message once they load.")
                .font(Theme.font(13)).foregroundStyle(Theme.muted)
            Button { Task { await model.refresh() } } label: {
                Text(model.isLoading ? "Trying…" : "Try again").font(Theme.font(13, .semibold)).foregroundStyle(Theme.brand)
                    .frame(minWidth: 120, minHeight: 44, alignment: .leading).contentShape(Rectangle())
            }.buttonStyle(PressStyle()).disabled(model.isLoading).accessibilityIdentifier("send-retry")
        }.orchCard().padding(.top, 26)
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("No workspaces yet").font(Theme.font(15, .semibold))
            Text("There is nowhere to send a message yet. Ask the person who invited you to add a workspace.")
                .font(Theme.font(13)).foregroundStyle(Theme.muted)
            Button { Task { await model.refresh() } } label: {
                Text(model.isLoading ? "Checking…" : "Check again").font(Theme.font(13, .semibold)).foregroundStyle(Theme.brand)
                    .frame(minWidth: 120, minHeight: 44, alignment: .leading).contentShape(Rectangle())
            }.buttonStyle(PressStyle()).disabled(model.isLoading)
        }.orchCard().padding(.top, 26)
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow(text: "TO WORKSPACE").padding(.top, 26)
            Menu {
                Picker("Send to", selection: $workspaceID) {
                    ForEach(model.workspaces) { ws in Text(optionTitle(ws)).tag(ws.id) }
                }
            } label: {
                HStack(spacing: 8) {
                    Text(model.workspaces.first { $0.id == workspaceID }.map(optionTitle) ?? "No workspaces")
                        .font(Theme.font(15)).foregroundStyle(Theme.text).multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.up.chevron.down").font(Theme.font(12)).foregroundStyle(Theme.muted)
                }.padding(.horizontal, 12).padding(.vertical, 8)
                    .frame(maxWidth: .infinity, minHeight: 48, alignment: .leading)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.borderStrong))
                    .contentShape(Rectangle())
            }.accessibilityLabel("Send to").accessibilityValue(model.workspaces.first { $0.id == workspaceID }.map(optionTitle) ?? "No workspaces")
                .accessibilityIdentifier("workspace-picker")
                .disabled(sending || recording || transcribing)
            Eyebrow(text: "YOUR MESSAGE").padding(.top, 16)
            ZStack(alignment: .topLeading) {
                if text.isEmpty {
                    Text(recording ? "Recording your voice…" : transcribing ? "Writing it down…" : "Speak, or type what you would like to get done.").foregroundStyle(Theme.muted)
                        .padding(.horizontal, 5).padding(.top, 8).allowsHitTesting(false)
                }
                TextEditor(text: $text).scrollContentBackground(.hidden).focused($editing)
                    .accessibilityIdentifier("transcript").accessibilityLabel("Your message")
                    .disabled(recording || transcribing || sending)
            }.font(Theme.font(13)).padding(10).frame(minHeight: editorHeight, maxHeight: editorHeight)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.borderStrong))
            VStack(spacing: 12) {
                if !editing { HStack(spacing: 16) {
                    ForEach(Array((voice?.levels ?? []).enumerated()), id: \.offset) { _, level in
                        Capsule().fill(Theme.brand.opacity(recording ? 0.9 : 0.3)).frame(width: 3, height: 4 + 26 * level)
                            .animation(reduceMotion ? nil : .easeOut(duration: 0.08), value: level)
                    }
                }.frame(height: 32).accessibilityIdentifier("level-meter")
                    .accessibilityValue(recording ? "recording" : "idle") }
                Button {
                    toggling = true
                    Task {
                        await voice?.toggle(current: text)
                        if model.tab != .send { voice?.stop() }
                        toggling = false
                    }
                } label: {
                    Image(systemName: recording ? "stop.fill" : "mic.fill").font(Theme.font(editing ? 21 : 27))
                        .foregroundStyle(recording ? Theme.danger : Theme.brand)
                        .frame(width: editing ? 52 : 70, height: editing ? 52 : 70)
                        .background((recording ? Theme.danger : Theme.brand).opacity(0.1), in: Circle())
                        .overlay(Circle().stroke((recording ? Theme.danger : Theme.brand).opacity(0.3)))
                        .overlay {
                            if recording {
                                Circle().stroke(Theme.danger.opacity(0.7), lineWidth: 3)
                                    .scaleEffect(reduceMotion ? 1.1 : (pulse ? 1.15 : 1))
                                    .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: pulse)
                            }
                        }
                }.buttonStyle(.plain).accessibilityIdentifier("mic")
                    .accessibilityLabel(micLabel)
                    .disabled(voice == nil || toggling || transcribing || sending)
                Text(micLabel).font(Theme.font(12, .medium)).accessibilityIdentifier("mic-status")
                if !editing, !text.isEmpty, !recording, !transcribing, voice?.error == nil {
                    Text("Tap the text to fix anything before you send.").font(.caption).foregroundStyle(Theme.muted)
                }
                if let error = voice?.error { Text(error).font(.caption).foregroundStyle(Theme.danger) }
            }.frame(maxWidth: .infinity).padding(.top, 5).padding(.bottom, editing ? 6 : 16)
            let canSend = !(recording || transcribing || toggling || sending || workspaceID.isEmpty || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            Button(sending ? "Sending…" : "Send to inbox ↑") {
                guard canSend else { showHint = true; return }
                showHint = false
                sending = true
                Task {
                    if await model.send(to: workspaceID, text: text) { sent = model.lastSent }
                    sending = false
                }
            }.buttonStyle(PrimaryButtonStyle(muted: !canSend)).accessibilityIdentifier("send-button")
                .disabled(sending)
            if showHint, !canSend {
                Text(hintText).font(Theme.font(12)).foregroundStyle(Theme.danger).frame(maxWidth: .infinity)
                    .accessibilityIdentifier("send-hint")
            }
            Text("Your workspace will pick it up from here.").font(Theme.font(11))
                .foregroundStyle(Theme.muted).frame(maxWidth: .infinity).padding(.top, 2)
        }
    }

    private func sentState(_ note: AppModel.SentNote) -> some View {
        VStack(spacing: 12) {
            Image(systemName: "checkmark").font(Theme.font(28)).foregroundStyle(Theme.brand)
                .frame(width: 72, height: 72).background(Theme.brand.opacity(0.07), in: Circle())
                .overlay(Circle().stroke(Theme.brand.opacity(0.33))).padding(.bottom, 13)
            Text("It's in the inbox.").font(Theme.font(25, .semibold))
            Text("Sent to \(note.workspaceName)").font(Theme.font(13)).foregroundStyle(Theme.muted)
            VStack(alignment: .leading, spacing: 4) {
                Text("You sent:").font(Theme.font(11)).foregroundStyle(Theme.muted)
                Text(note.text).font(Theme.font(14)).foregroundStyle(Theme.text)
            }.padding(.leading, 12).frame(maxWidth: .infinity, alignment: .leading)
                .overlay(alignment: .leading) { Rectangle().fill(Theme.brand).frame(width: 3) }
                .padding(.vertical, 16)
            Button("Send another message") { sent = nil; text = "" }.buttonStyle(SecondaryButtonStyle())
            Button("Back to home →") { model.tab = .home }
                .buttonStyle(WideButtonStyle(color: Theme.muted)).font(Theme.font(13))
        }.frame(maxWidth: .infinity).padding(.top, 48)
    }

    private func optionTitle(_ ws: Workspace) -> String {
        let twins = model.workspaces.filter { $0.displayName == ws.displayName }.count > 1
        let hint = ws.description?.split(separator: " ").prefix(3).joined(separator: " ") ?? ""
        return twins && !hint.isEmpty ? "\(ws.displayName) (\(hint))" : ws.displayName
    }

    private func selectWorkspace(preferFilter: Bool = false) {
        if (preferFilter || workspaceID.isEmpty), let filter = model.questionFilter,
           model.workspaces.contains(where: { $0.id == filter }) { workspaceID = filter }
        if !model.workspaces.contains(where: { $0.id == workspaceID }) { workspaceID = model.workspaces.first?.id ?? "" }
    }
}
