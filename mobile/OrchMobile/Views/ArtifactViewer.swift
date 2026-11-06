import SwiftUI

struct ArtifactApproval {
    let question: Question
    let option: String
    let context: String
}

@MainActor
struct ArtifactViewer: View {
    let item: ArtifactItem
    var approval: ArtifactApproval? = nil
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @Environment(\.artifactLoader) private var loader
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var store = PinStore()
    @State private var commentMode = false
    @State private var loadState: LoadState = .loading
    @State private var retry = 0
    @State private var sending = false
    @State private var sendError: String?
    @State private var temporaryDirectory: URL?

    private enum LoadState {
        case loading
        case ready(ArtifactSurfaceContent)
        case failed(String)
    }

    init(item: ArtifactItem, approval: ArtifactApproval? = nil) {
        self.item = item
        self.approval = approval
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 16) {
                Text(item.title).themeFont(20, .semibold).frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityAddTraits(.isHeader)
                Button { dismiss() } label: {
                    Image(systemName: "xmark").themeFont(18)
                        .foregroundStyle(Theme.muted).frame(width: 44, height: 44)
                        .background(Theme.surface3, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Close")
                .accessibilityIdentifier("artifact-close")
            }
            Text(item.subtitle).themeFont(14).foregroundStyle(Theme.muted)
            if commentMode {
                Text("Tap the preview to add a comment").themeFont(14).foregroundStyle(Theme.muted)
                if !store.pins.isEmpty { PinChipRow(store: store) }
            }
            preview
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Theme.surface)
                .clipShape(RoundedRectangle(cornerRadius: 14))
            if !commentMode, let approval {
                VStack(spacing: 6) {
                    Button {
                        model.chooseAnswer(approval.question, approval.option)
                        dismiss()
                    } label: {
                        Text("Approve publishing").themeFont(16, .semibold)
                            .frame(maxWidth: .infinity, minHeight: 50)
                            .foregroundStyle(Theme.onBrand)
                            .background(Theme.brand, in: RoundedRectangle(cornerRadius: 12))
                    }
                    .buttonStyle(.plain)
                    .disabled(sending)
                    .accessibilityIdentifier("artifact-approve-publishing")
                    Text("Answers the question in \(approval.context)")
                        .themeFont(13).foregroundStyle(Theme.muted)
                }
            }
            if item.canGiveFeedback {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 24) { bottomButtons }
                    VStack(spacing: 0) { bottomButtons }
                }
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(Theme.surface)
                .buttonStyle(ArtifactTextButtonStyle())
                .disabled(sending)
            }
            if let sendError { Text(sendError).themeFont(14).foregroundStyle(Theme.muted) }
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
        .padding(.bottom, 8)
        .background(Theme.bg)
        .foregroundStyle(Theme.text)
        .preferredColorScheme(.dark)
        .transaction { if reduceMotion { $0.animation = nil } }
        .task(id: item.id) { await load() }
        .task(id: retry) { if retry > 0 { await load() } }
        .sheet(isPresented: Binding(get: { store.editing != nil }, set: { if !$0 { store.cancelEdit() } })) {
            PinEditorSheet(store: store)
        }
        .onDisappear {
            if let temporaryDirectory { try? FileManager.default.removeItem(at: temporaryDirectory) }
            for pin in store.pins { if let url = pin.voiceFile { try? FileManager.default.removeItem(at: url) } }
        }
    }

    @ViewBuilder private var bottomButtons: some View {
        if commentMode {
            Button("Cancel") {
                for pin in store.pins { if let url = pin.voiceFile { try? FileManager.default.removeItem(at: url) } }
                store.reset(); commentMode = false; sendError = nil
            }
                .accessibilityIdentifier("artifact-cancel-comments")
            Button("Send comments (\(store.count))") { send(store.changesDraft(for: item)) }
                .disabled(store.count == 0)
                .accessibilityIdentifier("artifact-send-comments")
        } else {
            Button { send(PinStore.approveDraft(for: item)) } label: {
                Label("Looks good", systemImage: "hand.thumbsup")
            }.accessibilityIdentifier("artifact-looks-good")
            if canComment {
                Button("Comment") { commentMode = true; sendError = nil }
                    .accessibilityIdentifier("artifact-comment")
            }
        }
    }

    private var canComment: Bool {
        guard case .ready(let content) = loadState else { return false }
        switch content {
        case .web, .publish(.page), .publish(.bundle): return true
        case .data(_, _, let mime): return mime == "application/pdf" || mime.hasPrefix("image/")
        case .publish(.file(let file)): return file.type == "application/pdf" || file.type.hasPrefix("image/")
        case .quickLook, .link: return false
        }
    }

    @ViewBuilder private var preview: some View {
        switch loadState {
        case .loading: ProgressView().tint(Theme.brand).accessibilityLabel("Loading preview")
        case .failed(let message):
            VStack(spacing: 16) {
                Text(message).themeFont(16).multilineTextAlignment(.center)
                Button("Try again") { retry += 1 }.buttonStyle(ArtifactTextButtonStyle())
            }.padding(20)
        case .ready(let content): surface(content)
        }
    }

    @ViewBuilder private func surface(_ content: ArtifactSurfaceContent) -> some View {
        switch content {
        case .web, .publish(.page), .publish(.bundle):
            HTMLSurface(content: content, commentMode: commentMode, store: store) { loadState = .failed($0) }
        case .data(let data, _, let mime):
            if mime == "application/pdf" { PDFSurface(data: data, commentMode: commentMode, store: store) }
            else { ImageSurface(data: data, commentMode: commentMode, store: store) }
        case .publish(.file(let file)):
            if file.type == "application/pdf" { PDFSurface(data: file.bytes, commentMode: commentMode, store: store) }
            else if file.type.hasPrefix("image/") { ImageSurface(data: file.bytes, commentMode: commentMode, store: store) }
        case .quickLook(let url): QuickLookPreview(url: url)
        case .link(let url):
            Button("Open in Safari") { openURL(url) }.buttonStyle(ArtifactTextButtonStyle())
        }
    }

    private func load() async {
        loadState = .loading
        do {
            let content: ArtifactSurfaceContent
            switch item.kind {
            case .html:
                guard let url = item.url else { throw PublishError.broken }
                if let link = PublishLink(url) {
                    let published = try await loader.publish(link)
                    if case .file(let file) = published, file.type != "application/pdf", !file.type.hasPrefix("image/") {
                        content = try fileContent(file.bytes, name: file.name, mime: file.type)
                    } else { content = .publish(published) }
                } else { content = .web(url) }
            case .pdf, .image, .file:
                guard let id = item.blobId, let data = await (loader.blob?(id) ?? model.blob(id)) else {
                    if !Task.isCancelled { loadState = .failed("Could not load this file. Check your connection and try again.") }
                    return
                }
                let mime = item.kind == .pdf ? "application/pdf" : (item.mime ?? (item.kind == .image ? "image/*" : "application/octet-stream"))
                content = try fileContent(data, name: item.name ?? item.title, mime: mime)
            case .link:
                guard let url = item.url else { throw PublishError.broken }
                content = .link(url)
            }
            guard !Task.isCancelled else { return }
            loadState = .ready(content)
        } catch {
            guard !Task.isCancelled else { return }
            loadState = .failed(error.localizedDescription)
        }
    }

    private func fileContent(_ bytes: Data, name: String, mime: String) throws -> ArtifactSurfaceContent {
        if mime == "application/pdf" || mime.hasPrefix("image/") { return .data(bytes, name: name, mime: mime) }
        if mime.hasPrefix("text/html"), let html = String(data: bytes, encoding: .utf8) { return .publish(.page(html: html, name: name)) }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("orch-preview-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let url = folder.appendingPathComponent(Outbox.safeFileName(name))
        do { try bytes.write(to: url, options: .atomic) }
        catch { try? FileManager.default.removeItem(at: folder); throw error }
        if let temporaryDirectory { try? FileManager.default.removeItem(at: temporaryDirectory) }
        temporaryDirectory = folder
        return .quickLook(url)
    }

    private func send(_ feedback: DraftFeedback?) {
        guard !sending, let feedback, let target = item.conversation?.target else { return }
        sending = true; sendError = nil
        Task { @MainActor in
            defer { sending = false }
            do { try await model.send(MessageDraft(feedback: feedback), to: target); dismiss() }
            catch let problem as SendRequest.Problem {
                switch problem {
                case .attachmentTooBig: sendError = "A voice comment is too large to send. Record a shorter comment."
                case .nothingToSend, .badFeedback: sendError = "Add text or a voice recording to each comment before sending."
                case .badTarget, .feedbackNeedsTicket, .generalWithTicket: sendError = "These comments need a topic to send to."
                default: sendError = "Could not send this feedback. Please try again."
                }
            } catch { sendError = "Could not send this feedback. Please try again." }
        }
    }
}

private struct ArtifactTextButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.themeFont(16, .semibold)
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 12).frame(minHeight: 44)
            .foregroundStyle(enabled ? Theme.brand : Theme.muted)
            .opacity(configuration.isPressed ? 0.65 : 1)
    }
}
