import SwiftUI
import AVFoundation
import UIKit

struct QRScannerView: View {
    @Environment(\.dismiss) private var dismiss
    let onCode: (String) -> Void
    @State private var unavailable = false

    var body: some View {
        VStack(spacing: 20) {
            if unavailable {
                Text("No camera here. Use the invitation link.")
                    .font(Theme.font(17)).multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScannerCamera(onCode: onCode, onUnavailable: { unavailable = true })
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .accessibilityLabel("Scan invitation QR code")
            }
            Button("Close") { dismiss() }.buttonStyle(SecondaryButtonStyle())
        }.padding(23).foregroundStyle(Theme.text).background(Theme.bg).preferredColorScheme(.dark)
    }
}

private struct ScannerCamera: UIViewControllerRepresentable {
    let onCode: (String) -> Void
    let onUnavailable: () -> Void

    func makeUIViewController(context: Context) -> ScannerController {
        ScannerController(onCode: onCode, onUnavailable: onUnavailable)
    }
    func updateUIViewController(_ controller: ScannerController, context: Context) {}
    static func dismantleUIViewController(_ controller: ScannerController, coordinator: ()) { controller.stop() }
}

@MainActor
private final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    private let driver = CameraSessionDriver()
    private let onCode: (String) -> Void
    private let onUnavailable: () -> Void
    private var preview: AVCaptureVideoPreviewLayer?
    private var permissionTask: Task<Void, Never>?
    private var finished = false

    init(onCode: @escaping (String) -> Void, onUnavailable: @escaping () -> Void) {
        self.onCode = onCode
        self.onUnavailable = onUnavailable
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(Theme.bg)
        #if targetEnvironment(simulator)
        onUnavailable()
        #else
        permissionTask = Task { [weak self] in
            guard let self else { return }
            guard AVCaptureDevice.default(for: .video) != nil else { onUnavailable(); return }
            let authorized: Bool
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized: authorized = true
            case .notDetermined: authorized = await AVCaptureDevice.requestAccess(for: .video)
            default: authorized = false
            }
            guard !Task.isCancelled else { return }
            guard authorized else { onUnavailable(); return }
            let layer = AVCaptureVideoPreviewLayer(session: driver.session)
            layer.videoGravity = .resizeAspectFill
            layer.frame = view.bounds
            view.layer.addSublayer(layer)
            preview = layer
            driver.start(delegate: self) { [weak self] success in
                guard let self, !finished else { return }
                if !success { onUnavailable() }
            }
        }
        #endif
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview?.frame = view.bounds
    }

    func stop() {
        finished = true
        permissionTask?.cancel()
        permissionTask = nil
        driver.stop()
    }

    nonisolated func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard let code = metadataObjects.compactMap({ ($0 as? AVMetadataMachineReadableCodeObject)?.stringValue }).first else { return }
        Task { @MainActor [weak self] in
            guard let self, !finished else { return }
            stop()
            onCode(code)
        }
    }
}

// Session configuration and running state are confined to this serial queue.
// The main actor only attaches the session to its preview layer before starting it.
private final class CameraSessionDriver: @unchecked Sendable {
    let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "orch.camera")

    func start(delegate: ScannerController, completion: @escaping @MainActor @Sendable (Bool) -> Void) {
        queue.async { [self] in
            session.beginConfiguration()
            guard let camera = AVCaptureDevice.default(for: .video),
                  let input = try? AVCaptureDeviceInput(device: camera), session.canAddInput(input) else {
                session.commitConfiguration()
                Task { @MainActor in completion(false) }
                return
            }
            session.addInput(input)
            let output = AVCaptureMetadataOutput()
            guard session.canAddOutput(output) else {
                session.commitConfiguration()
                Task { @MainActor in completion(false) }
                return
            }
            session.addOutput(output)
            output.setMetadataObjectsDelegate(delegate, queue: .main)
            guard output.availableMetadataObjectTypes.contains(.qr) else {
                session.commitConfiguration()
                Task { @MainActor in completion(false) }
                return
            }
            output.metadataObjectTypes = [.qr]
            session.commitConfiguration()
            session.startRunning()
            Task { @MainActor in completion(true) }
        }
    }

    func stop() {
        queue.async { [self] in
            if session.isRunning { session.stopRunning() }
            for output in session.outputs {
                (output as? AVCaptureMetadataOutput)?.setMetadataObjectsDelegate(nil, queue: nil)
            }
        }
    }
}
