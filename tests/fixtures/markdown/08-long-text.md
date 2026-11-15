# Texto largo

La conversión de documentos exige determinismo porque un mismo original debe producir exactamente el mismo resultado en cualquier máquina y en cualquier momento. Si la salida dependiera del reloj, del orden de un diccionario o de una ruta absoluta, dos ejecuciones equivalentes podrían diferir y la verificación perdería sentido.

El párrafo anterior se repite con variaciones mínimas para simular un documento extenso que ocupa más de una página y obliga al motor de composición a decidir cortes de línea y de página. La decisión de composición puede cambiar el PDF, pero nunca el LaTeX generado.

Un tercer párrafo cierra el cuerpo. La densidad de texto permite comprobar que el generador no introduce pérdidas, truncamientos ni transformaciones silenciosas: cada oración debe estar presente en la salida y cada carácter especial debe aparecer escapado una sola vez.
