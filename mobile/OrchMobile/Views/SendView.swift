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

    private var recording: Bool { voice?.isRecording == true }
    private var transcribing: Bool { voice?.isTranscribing == true }
    private var micLabel: String { recording ? "Recording your voice… tap to stop" : transcribing ? "Writing it down…" : "Tap to speak" }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                ScreenHeading(title: "Say it. Send it.", subtitle: "A thought, a request, a next step.").padding(.top, 14)
                if let sent { sentState(sent) } else { composer }
                ModelMessage().padding(.top, 12)
            }.padding(.horizontal, 23).padding(.top, 6).padding(.bottom, 20)
        }
        .task {
            if voice == nil { let m = model; voice = VoiceInput(mode: model.voiceMode, transcribe: { try await m.transcribe($0) }) }
            selectWorkspace()
            if UserDefaults.standard.bool(forKey: "autoMic") { await voice?.toggle(current: text) }
        }
        .onChange(of: model.workspaces) { _, _ in selectWorkspace() }
        .onChange(of: model.tab) { _, tab in
            if tab == .send { selectWorkspace(preferFilter: true) }
            else { voice?.stop() }
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

    private var composer: some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow(text: "SEND TO").padding(.top, 26)
            Picker("Send to", selection: $workspaceID) {
                if model.workspaces.isEmpty { Text("No workspaces").tag("") }
                ForEach(model.workspaces) { ws in
                    let twins = model.workspaces.filter { $0.displayName == ws.displayName }.count > 1
                    let hint = ws.description?.split(separator: " ").prefix(3).joined(separator: " ") ?? ""
                    Text(twins && !hint.isEmpty ? "\(ws.displayName) (\(hint))" : ws.displayName).tag(ws.id)
                }
            }.pickerStyle(.menu).tint(Theme.text)
                .frame(maxWidth: .infinity, minHeight: 48, alignment: .leading)
                .padding(.horizontal, 10).background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border))
                .disabled(sending || recording || transcribing)
            Eyebrow(text: "YOUR MESSAGE").padding(.top, 16)
            ZStack(alignment: .topLeading) {
                if text.isEmpty {
                    Text(recording ? "Recording your voice…" : transcribing ? "Writing it down…" : "Speak, or type what you would like to get done.").foregroundStyle(Theme.muted)
                        .padding(.horizontal, 5).padding(.top, 8).allowsHitTesting(false)
                }
                TextEditor(text: $text).scrollContentBackground(.hidden)
                    .accessibilityIdentifier("transcript").accessibilityLabel("Your message")
                    .disabled(recording || transcribing || sending)
            }.font(Theme.font(13)).padding(10).frame(height: 137)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border))
            VStack(spacing: 12) {
                HStack(spacing: 16) {
                    ForEach(Array((voice?.levels ?? []).enumerated()), id: \.offset) { _, level in
                        Capsule().fill(Theme.brand.opacity(recording ? 0.9 : 0.3)).frame(width: 3, height: 4 + 26 * level)
                            .animation(reduceMotion ? nil : .easeOut(duration: 0.08), value: level)
                    }
                }.frame(height: 32).accessibilityIdentifier("level-meter")
                    .accessibilityValue(recording ? "recording" : "idle")
                Button {
                    toggling = true
                    Task {
                        await voice?.toggle(current: text)
                        if model.tab != .send { voice?.stop() }
                        toggling = false
                    }
                } label: {
                    Image(systemName: recording ? "stop.fill" : "mic.fill").font(Theme.font(27))
                        .foregroundStyle(recording ? Theme.danger : Theme.brand)
                        .frame(width: 70, height: 70)
                        .background((recording ? Theme.danger : Theme.brand).opacity(0.1), in: Circle())
                        .overlay(Circle().stroke((recording ? Theme.danger : Theme.brand).opacity(0.3)))
                        .overlay {
                            if recording {
                                Circle().stroke(Theme.danger.opacity(pulse ? 0.2 : 0.6), lineWidth: 3)
                                    .scaleEffect(pulse ? 1.2 : 1)
                                    .animation(reduceMotion ? nil : .easeInOut(duration: 0.8).repeatForever(autoreverses: true), value: pulse)
                            }
                        }
                }.buttonStyle(.plain).accessibilityIdentifier("mic")
                    .accessibilityLabel(micLabel)
                    .disabled(voice == nil || toggling || transcribing || sending)
                Text(micLabel).font(Theme.font(12, .medium)).accessibilityIdentifier("mic-status")
                if !text.isEmpty, !recording, !transcribing, voice?.error == nil {
                    Text("Tap the text to fix anything before you send.").font(.caption).foregroundStyle(Theme.muted)
                }
                if let error = voice?.error { Text(error).font(.caption).foregroundStyle(Theme.danger) }
            }.frame(maxWidth: .infinity).padding(.top, 5).padding(.bottom, 16)
            let canSend = !(recording || transcribing || toggling || sending || workspaceID.isEmpty || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            Button(sending ? "Sending…" : "Send to inbox ↑") {
                sending = true
                Task {
                    if await model.send(to: workspaceID, text: text) { sent = model.lastSent }
                    sending = false
                }
            }.buttonStyle(PrimaryButtonStyle(muted: !canSend)).accessibilityIdentifier("send-button")
                .disabled(!canSend)
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
                .font(Theme.font(13)).foregroundStyle(Theme.muted).frame(minHeight: 44)
        }.frame(maxWidth: .infinity).padding(.top, 48)
    }

    private func selectWorkspace(preferFilter: Bool = false) {
        if (preferFilter || workspaceID.isEmpty), let filter = model.questionFilter,
           model.workspaces.contains(where: { $0.id == filter }) { workspaceID = filter }
        if !model.workspaces.contains(where: { $0.id == workspaceID }) { workspaceID = model.workspaces.first?.id ?? "" }
    }
}
