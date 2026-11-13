import SwiftUI
import PDFKit

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
    @State private var shareURL: URL?
    @State private var pageCount: Int?
    @State private var showDetails = false

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
                if let shareURL {
                    ShareLink(item: shareURL) {
                        Image(systemName: "square.and.arrow.up").themeFont(18)
                            .foregroundStyle(Theme.muted).frame(width: 44, height: 44)
                            .background(Theme.surface3, in: Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Share")
                    .accessibilityIdentifier("artifact-share")
                }
                Button { dismiss() } label: {
                    Image(systemName: "xmark").themeFont(18)
                        .foregroundStyle(Theme.muted).frame(width: 44, height: 44)
                        .background(Theme.surface3, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Close")
                .accessibilityIdentifier("artifact-close")
            }
            HStack(spacing: 8) {
                Text(item.subtitle(pages: pageCount)).themeFont(14).foregroundStyle(Theme.muted)
                    .accessibilityIdentifier("artifact-subtitle")
                if let version = item.versionDetail {
                    Button(showDetails ? version : "Details") { showDetails.toggle() }
                        .themeFont(13).foregroundStyle(Theme.muted).frame(minHeight: 44)
                        .accessibilityIdentifier("artifact-details")
                }
            }
            if commentMode {
                Text("Tap the preview to add a comment").themeFont(14).foregroundStyle(Theme.muted)
                if !store.pins.isEmpty { PinChipRow(store: store) }
            }
            preview
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Theme.bg)
                .padding(.horizontal, -16)   // edge to edge on the dark background
                .overlay(alignment: .bottom) {
                    if let pageCount, pageCount > 1 {
                        Text("\(pageCount) pages").themeFont(13).foregroundStyle(Theme.text)
                            .padding(.horizontal, 10).padding(.vertical, 4)
                            .background(Theme.surface3.opacity(0.9), in: Capsule()).padding(.bottom, 8)
                            .accessibilityIdentifier("artifact-page-count")
                    }
                }
            if !commentMode, let approval {
                VStack(spacing: 6) {
                    Button {
                        let q = approval.question
                        if model.answers[q.id] != nil || model.pendingAnswers[q.id] != nil {
                            sendError = "This question has already been answered."
                        } else {
                            model.chooseAnswer(q, approval.option)
                            if model.pendingAnswers[q.id] != nil || model.answers[q.id] != nil { dismiss() }
                            else { sendError = "Could not send your approval. Try again." }
                        }
                    } label: {
                        Text("Approve publishing").themeFont(16, .semibold)
                            .frame(maxWidth: .infinity, minHeight: 50)
                            .foregroundStyle(Theme.onBrand)
                            .background(Theme.brand, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("artifact-approve-publishing")
                    Text("Answers the question in \(approval.context)")
                        .themeFont(13).foregroundStyle(Theme.muted)
                }
            }
            if item.canGiveFeedback {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 10) { bottomButtons }
                    VStack(spacing: 10) { bottomButtons }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8).padding(.horizontal, 16)
                .background(Theme.surface)   // same band as the chat composer bar
                .padding(.horizontal, -16)
                .buttonStyle(ArtifactActionButtonStyle())
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
            Button("Add comment here") { store.addAtCenter?() }
                .accessibilityHint("Adds a comment in the middle of what is on screen")
                .accessibilityIdentifier("artifact-add-pin")
            Button("Send comments (\(store.count))") { send(store.changesDraft(for: item)) }
                .disabled(store.count == 0)
                .accessibilityIdentifier("artifact-send-comments")
                .buttonStyle(ArtifactActionButtonStyle(primary: true))
        } else {
            Button { send(PinStore.approveDraft(for: item)) } label: {
                Label("Looks good", systemImage: "checkmark")
            }.disabled(!canApprove).accessibilityIdentifier("artifact-looks-good")
                .buttonStyle(ArtifactActionButtonStyle(primary: true))
            if canComment {
                Button("Comment") { commentMode = true; sendError = nil }
                    .accessibilityIdentifier("artifact-comment")
            }
        }
    }

    /// "Looks good" only once the content is on screen: never approve something that was not seen.
    private var canApprove: Bool {
        guard case .ready(let content) = loadState else { return false }
        switch content { case .quickLook, .shareOnly, .link: return false; default: return true }
    }

    private var canComment: Bool {
        guard case .ready(let content) = loadState else { return false }
        switch content {
        case .publish(.page), .publish(.bundle): return true
        case .data(_, _, let mime): return mime == "application/pdf" || mime.hasPrefix("image/")
        case .publish(.file(let file)): return file.type == "application/pdf" || file.type.hasPrefix("image/")
        case .quickLook, .shareOnly, .link: return false
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
        case .publish(.page), .publish(.bundle):
            HTMLSurface(content: content, commentMode: commentMode, store: store) { loadState = .failed($0) }
        case .data(let data, _, let mime):
            if mime == "application/pdf" { PDFSurface(data: data, commentMode: commentMode, store: store) }
            else { ImageSurface(data: data, commentMode: commentMode, store: store) }
        case .publish(.file(let file)):
            if file.type == "application/pdf" { PDFSurface(data: file.bytes, commentMode: commentMode, store: store) }
            else if file.type.hasPrefix("image/") { ImageSurface(data: file.bytes, commentMode: commentMode, store: store) }
        case .quickLook(let url): QuickLookPreview(url: url)
        case .shareOnly(let url, let name, let size):
            VStack(spacing: 14) {
                Image(systemName: "doc").themeFont(40).foregroundStyle(Theme.muted)
                Text(name).themeFont(17, .semibold).multilineTextAlignment(.center)
                Text(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file)).themeFont(14).foregroundStyle(Theme.muted)
                ShareLink(item: url) { Label("Open in Files", systemImage: "square.and.arrow.up") }
                    .buttonStyle(ArtifactTextButtonStyle()).accessibilityIdentifier("artifact-share-file")
            }.padding(20)
        case .link(let url):
            Button("Open in Safari") { if let safe = SafeLink.url(url.absoluteString) { openURL(safe) } }.buttonStyle(ArtifactTextButtonStyle())
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
                } else if ["http", "https"].contains(url.scheme?.lowercased()) {
                    content = .link(url)   // an app or any other page: the external browser, never in-app (no pins there in v3)
                } else { throw PublishError.broken }
            case .pdf, .image, .file:
                let loaded: Data?
                if let id = item.blobId { if let custom = loader.blob, let data = await custom(id) { loaded = data } else { loaded = await model.blob(id) } } else { loaded = nil }
                guard let data = loaded else {
                    if !Task.isCancelled { loadState = .failed("Could not load this file. Check your connection and try again.") }
                    return
                }
                let mime = item.kind == .pdf ? "application/pdf" : (item.mime ?? (item.kind == .image ? "image/*" : "application/octet-stream"))
                content = try fileContent(data, name: item.name ?? item.title, mime: mime)
            case .link:
                guard let url = item.url, ["http", "https"].contains(url.scheme?.lowercased()) else { throw PublishError.broken }
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
        if mime.hasPrefix("text/html"), let html = String(data: bytes, encoding: .utf8) { return .publish(.page(html: html, name: name)) }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("orch-preview-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let safe = ArtifactItem.previewName(name).safe
        let url = folder.appendingPathComponent(safe)
        do { try bytes.write(to: url, options: .atomic) }
        catch { try? FileManager.default.removeItem(at: folder); throw error }
        if let temporaryDirectory { try? FileManager.default.removeItem(at: temporaryDirectory) }
        temporaryDirectory = folder
        shareURL = url   // the share icon in the top bar, also for PDFs and pictures
        if mime == "application/pdf" {
            pageCount = PDFDocument(data: bytes)?.pageCount
            return .data(bytes, name: name, mime: mime)
        }
        if mime.hasPrefix("image/") { return .data(bytes, name: name, mime: mime) }
        return ArtifactItem.canPreview(fileName: url.lastPathComponent) ? .quickLook(url) : .shareOnly(url, name: name, size: bytes.count)
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

struct ArtifactActionButtonStyle: ButtonStyle {
    var primary = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.themeFont(16, .semibold)
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 12).frame(maxWidth: .infinity, minHeight: 50)
            .foregroundStyle(primary ? Theme.onBrand : Theme.text)
            .background(primary ? Theme.brand : Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).stroke(primary ? Color.clear : Theme.border))
            .opacity(!enabled ? 0.45 : configuration.isPressed ? 0.65 : 1)
    }
}
