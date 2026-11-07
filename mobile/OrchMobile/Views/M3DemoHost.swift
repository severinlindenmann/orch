#if DEBUG
import PDFKit
import SwiftUI

/// Debug host for the M3 screens (artifact viewer, media picker, info): `-m3Host viewer-html|viewer-pdf|viewer-image|picker|info`
/// with `-relayMode mock -seedPaired YES`. Used by the UI tests and the Simulator screenshots; not part of the release app.
struct M3DemoHost: View {
    let mode: String
    @Environment(AppModel.self) private var model
    @State private var item: ArtifactItem?
    @State private var showPicker = false
    @State private var showInfo = false
    @State private var picked = "nothing picked"

    private let topic = ConversationID.topic(workspace: "ws_pilatus001", ticket: "t_q3sum1")

    nonisolated static let samplePage = """
    <!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><body style="margin:0;background:#f6f1e6;color:#1d4a3a;font-family:Georgia,serif">
    <nav style="display:flex;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #c9d4c6"><b>rigi.</b><span>Made for the everyday</span></nav>
    <section id="hero" style="padding:24px 20px"><small>LESS, BUT BETTER</small><h1 style="font-size:46px;line-height:1.05;margin:10px 0">Good things. Simply made.</h1>
    <p style="font-size:18px;line-height:1.5">Considered essentials for a slower, brighter everyday. Designed in Switzerland, made to stay.</p>
    <p><a href="https://example.org/never" style="background:#1d4a3a;color:#fff;padding:14px 22px;border-radius:30px;display:inline-block">Explore the collection</a></p></section>
    <div style="height:700px;background:#5b8a74;border-radius:50% 50% 0 0"></div></body>
    """
    nonisolated static let publishURL = URL(string: "https://demo.orch.test/f/demo1#k=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8")!

    nonisolated static func samplePDF() -> Data {
        let r = UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 612, height: 792))
        return r.pdfData { c in
            for n in 1...2 {
                c.beginPage()
                ("Q3 board summary - page \(n)" as NSString).draw(at: CGPoint(x: 60, y: 80), withAttributes: [.font: UIFont.boldSystemFont(ofSize: 28)])
                ("The quarter, in perspective." as NSString).draw(at: CGPoint(x: 60, y: 140), withAttributes: [.font: UIFont.systemFont(ofSize: 18)])
            }
        }
    }

    private var loader: ArtifactLoader {
        ArtifactLoader(publish: { _ in .page(html: Self.samplePage, name: "landing.html") },
                       blob: { id in id == "b_pdf" ? Self.samplePDF() : nil })
    }
    private var items: [String: ArtifactItem] {
        ["viewer-html": ArtifactItem(id: "a_html", title: "Rigi - landing page", kind: .html, url: Self.publishURL, artifactId: "a_0123456789ab", rev: "r2abcdef1234", conversation: topic),
         "viewer-pdf": ArtifactItem(id: "a_pdf", title: "Q3 board summary", kind: .pdf, blobId: "b_pdf", name: "q3.pdf", artifactId: "a_aaaaaaaaaaaa", rev: "r1", conversation: topic),
         "viewer-image": ArtifactItem(id: "a_img", title: "q3-chart.png", kind: .image, blobId: "b_chart", name: "q3-chart.png", artifactId: "a_bbbbbbbbbbbb", rev: "r1", conversation: topic)]
    }
    private var feedbackCount: Int { model.conversationItems(topic).filter { $0.feedback != nil }.count }

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                if model.phase != .ready { ProgressView() } else {
                    Text("feedback sent: \(feedbackCount)").accessibilityIdentifier("demo-feedback-count")
                    Text(picked).accessibilityIdentifier("demo-picked")
                    if let i = items[mode] { Button("Open viewer") { item = i }.accessibilityIdentifier("demo-open") }
                    Button("Open picker") { showPicker = true }.accessibilityIdentifier("demo-open-picker")
                    NavigationLink("Open info", destination: ConversationInfoView(conversation: topic)).accessibilityIdentifier("demo-open-info")
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity).background(Theme.bg)
            .task(id: model.phase) {
                guard model.phase == .ready else { return }
                if let i = items[mode] { item = i }
                if mode == "picker" { showPicker = true }
            }
            .fullScreenCover(item: $item) { ArtifactViewer(item: $0).environment(\.artifactLoader, loader) }
            .sheet(isPresented: $showPicker) {
                MediaPicker { sel in
                    switch sel {
                    case .files(let f, let caption): picked = "files \(f.count) caption \(caption ?? "-")"
                    case .location(let l): picked = "location \(l.lat)"
                    }
                }.presentationDetents([.height(260), .medium])
            }
        }.preferredColorScheme(.dark)
    }
}
#endif
