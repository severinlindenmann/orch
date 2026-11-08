import SwiftUI

@MainActor
struct PinChipRow: View {
    let store: PinStore
    var body: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 8) {
                ForEach(store.pins) { pin in
                    HStack(spacing: 0) {
                        Button { store.edit(pin.n) } label: {
                            Text("\(number(pin.n)) \(pin.text.isEmpty ? "Voice comment" : pin.text)")
                                .lineLimit(1).frame(maxWidth: 220, alignment: .leading)
                                .padding(.leading, 12).frame(minHeight: 44)
                        }
                        .accessibilityLabel("Edit comment \(pin.n): \(pin.text.isEmpty ? "Voice comment" : pin.text)")
                        .accessibilityIdentifier("pin-chip-\(pin.n)")
                        Button {
                            if let url = pin.voiceFile { try? FileManager.default.removeItem(at: url) }
                            store.remove(pin.n)
                        } label: {
                            Image(systemName: "xmark").frame(width: 44, height: 44)
                        }
                        .accessibilityLabel("Delete comment \(pin.n)").accessibilityIdentifier("pin-chip-delete-\(pin.n)")
                    }
                    .background(Theme.surface3, in: Capsule(style: .continuous))
                }
            }
        }
        .scrollIndicators(.hidden)
        .themeFont(14)
        .foregroundStyle(Theme.text)
        .buttonStyle(.plain)
    }
    private func number(_ n: Int) -> String {
        if (1...20).contains(n), let scalar = UnicodeScalar(0x2460 + n - 1) { return String(scalar) }
        return "\(n)."
    }
}

@MainActor
struct PinEditorSheet: View {
    let store: PinStore
    @Environment(AppModel.self) private var model
    @State private var recorder: VoiceRecorder?
    @State private var working = false
    @State private var error: String?
    @State private var job: Task<Void, Never>?
    // Copies survive recorder.cancel(); unsaved copies are removed when the editor closes.
    @State private var ownedClips: [URL] = []
    @State private var savedClip: URL?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Pin \(store.editing?.n ?? 1)").themeFont(20, .semibold)
                        .accessibilityAddTraits(.isHeader)
                    Spacer()
                    Button(store.isEditingNew ? "Cancel" : "Delete") {
                        if store.isEditingNew { store.cancelEdit() }
                        else if let n = store.editing?.n {
                            if let url = store.pins.first(where: { $0.n == n })?.voiceFile {
                                try? FileManager.default.removeItem(at: url)
                            }
                            store.remove(n)
                        }
                    }
                    .accessibilityIdentifier(store.isEditingNew ? "pin-cancel" : "pin-delete")
                    .buttonStyle(PinTextButtonStyle())
                }
                Text("Your comment").themeFont(13).foregroundStyle(Theme.muted)
                TextField("What should change?", text: Binding(
                    get: { store.editing?.text ?? "" }, set: { store.editing?.text = $0 }), axis: .vertical)
                    .lineLimit(2...5)
                    .themeFont(16)
                    .padding(12)
                    .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                    .accessibilityLabel("What should change?")
                    .accessibilityIdentifier("pin-text")
                HStack(spacing: 12) {
                    Button { toggleMic() } label: {
                        Image(systemName: recorder?.isRecording == true ? "stop.fill" : "mic.fill")
                            .frame(width: 44, height: 44)
                            .background(Theme.surface3, in: Circle())
                    }
                    .accessibilityLabel(recorder?.isRecording == true ? "Stop recording" : "Record voice comment")
                    .accessibilityIdentifier("pin-mic")
                    .disabled(working)
                    Button("Save comment") {
                        let clip = store.editing?.voiceFile
                        let previous = store.pins.first(where: { $0.n == store.editing?.n })?.voiceFile
                        if store.saveEdit() {
                            savedClip = clip
                            if let previous, previous != clip { try? FileManager.default.removeItem(at: previous) }
                        }
                    }
                    .disabled(store.editing?.isComplete != true || working || recorder?.isRecording == true)
                    .accessibilityIdentifier("pin-save")
                    .buttonStyle(ArtifactActionButtonStyle(primary: true))
                }
                if let recorder, recorder.isRecording {
                    HStack(alignment: .center, spacing: 3) {
                        ForEach(Array(recorder.levels.enumerated()), id: \.offset) { _, level in
                            Capsule(style: .continuous).fill(Theme.brand).frame(width: 3, height: max(3, 24 * level))
                        }
                    }.frame(height: 24).accessibilityHidden(true)
                    Text("Recording \(Int(recorder.elapsed))s").themeFont(14).monospacedDigit()
                } else if working {
                    ProgressView().accessibilityLabel("Preparing voice comment")
                } else if store.editing?.voiceFile != nil {
                    Text("Voice comment").themeFont(14).foregroundStyle(Theme.muted)
                    Button {
                        store.editing?.voiceFile = nil
                        store.editing?.transcript = nil
                    } label: { Image(systemName: "xmark").frame(width: 44, height: 44) }
                    .accessibilityLabel("Remove voice comment")
                }
                if let message = error ?? recorder?.error {
                    Text(message).themeFont(14).foregroundStyle(Theme.muted)
                }
            }
            .padding(20)
        }
        .foregroundStyle(Theme.text)
        .tint(Theme.brand)
        .background(Theme.surface)
        .preferredColorScheme(.dark)
        .presentationDetents([.height(260), .medium])
        .presentationDragIndicator(.visible)
        .onDisappear {
            job?.cancel()
            recorder?.cancel()
            for url in ownedClips where url != savedClip { try? FileManager.default.removeItem(at: url) }
        }
    }

    private func toggleMic() {
        guard !working else { return }
        if recorder == nil { recorder = model.makeVoiceRecorder() }
        guard let recorder else { return }
        error = nil
        working = true
        job = Task { @MainActor in
            defer { working = false }
            if recorder.isRecording {
                guard let segment = recorder.stop().first else { return }
                let draft = await model.voiceDraft(for: segment)
                guard !Task.isCancelled, store.editing != nil else { return }
                do {
                    // The recorder owns segment.url and deletes it on disappearance.
                    let copy = FileManager.default.temporaryDirectory.appendingPathComponent("orch-pin-\(UUID().uuidString).m4a")
                    try FileManager.default.copyItem(at: segment.url, to: copy)
                    ownedClips.append(copy)
                    store.editing?.voiceFile = copy
                    store.editing?.transcript = draft.transcript
                    if store.editing?.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == true {
                        store.editing?.text = draft.transcript
                    }
                    recorder.cancel()
                } catch { self.error = "Could not save the voice comment. Try again." }
            } else {
                do {
                    try await recorder.start()
                    if Task.isCancelled { recorder.cancel() }
                } catch { self.error = recorder.error ?? "Could not start the microphone." }
            }
        }
    }
}

private struct PinTextButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.themeFont(16, .semibold)
            .foregroundStyle(enabled ? Theme.brand : Theme.muted)
            .padding(.horizontal, 12).frame(minHeight: 44)
            .opacity(configuration.isPressed ? 0.65 : 1)
    }
}
